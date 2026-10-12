//! Opening the proctor session, uploading the queue, and heartbeats
//! (`docs/api/contracts/proctoring.md`).
//!
//! Every request goes through [`ApiClient`], so each carries the interview-session token and a
//! DPoP proof signed by the device key.

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

use hv_api_client::{ApiClient, ApiError, Method, SessionManager};
use serde::{Deserialize, Serialize};
use tokio::sync::watch;
use tokio::task::JoinHandle;

use crate::event::ProctorEvent;
use crate::policy::SessionPolicy;
use crate::queue::EventQueue;

/// The problem code that ends a proctor session for good (the interview completed).
pub const SESSION_CLOSED: &str = "proctor-session-closed";

/// Anything that holds the [`ApiClient`]: the client itself, or the app's [`SessionManager`].
pub trait ApiSource: Send + Sync + 'static {
    fn api(&self) -> &ApiClient;
}

impl ApiSource for ApiClient {
    fn api(&self) -> &ApiClient {
        self
    }
}

impl ApiSource for SessionManager {
    fn api(&self) -> &ApiClient {
        SessionManager::api(self)
    }
}

/// `POST /proctoring/session`: opens (or, after a restart, reopens) the interview's proctor
/// session and returns its policy.
pub async fn open_session(
    api: &ApiClient,
    session_token: &str,
    interview_id: &str,
    app_version: &str,
) -> Result<SessionPolicy, ApiError> {
    #[derive(Serialize)]
    struct Body<'a> {
        interview_id: &'a str,
        app_version: &'a str,
    }
    api.send(
        Method::POST,
        "proctoring/session",
        Some(&Body {
            interview_id,
            app_version,
        }),
        Some(session_token),
    )
    .await
}

/// What a heartbeat reports besides `seq_high`, from the app's own state.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct DeviceStatus {
    /// `on`, `off`, …
    pub camera: String,
    pub mic: String,
    /// `capturing`, `stopped`, …
    pub screen: String,
    /// `connected`, `disconnected`, `not_required`, …
    pub third_eye: String,
    pub displays: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cpu_percent: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub vision_fps: Option<f32>,
}

/// How the uploader runs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UploaderConfig {
    pub batch_max_events: usize,
    pub heartbeat_interval: Duration,
    /// The first retry delay; it doubles per failure, with jitter, up to `backoff_max`.
    pub backoff_base: Duration,
    pub backoff_max: Duration,
    /// A server's `Retry-After` is honoured up to this.
    pub retry_after_max: Duration,
}

impl UploaderConfig {
    /// From the session policy, with the contracts README's backoff (exponential with jitter,
    /// capped at 30 s).
    pub fn from_policy(policy: &SessionPolicy) -> Self {
        Self {
            batch_max_events: policy.batch_max_events.max(1),
            heartbeat_interval: Duration::from_secs(policy.heartbeat_seconds.max(1)),
            ..Self::default()
        }
    }
}

impl Default for UploaderConfig {
    fn default() -> Self {
        Self {
            batch_max_events: 100,
            heartbeat_interval: Duration::from_secs(5),
            backoff_base: Duration::from_millis(500),
            backoff_max: Duration::from_secs(30),
            retry_after_max: Duration::from_secs(120),
        }
    }
}

/// What the uploader is doing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UploadState {
    /// Everything appended so far is acknowledged.
    Idle,
    Sending,
    /// The last attempt failed with this error code; it retries after a backoff.
    Retrying {
        code: String,
        attempt: u32,
    },
    /// The server closed the proctor session (the interview completed). Nothing more is sent.
    Closed,
    /// [`UploaderHandle::stop`] was called.
    Stopped,
}

struct Shared {
    api: Arc<dyn ApiSource>,
    queue: Arc<EventQueue>,
    session: String,
    token: Mutex<String>,
    resend: Mutex<BTreeSet<u64>>,
    state: watch::Sender<UploadState>,
    stop: watch::Sender<bool>,
    status: Arc<dyn Fn() -> DeviceStatus + Send + Sync>,
    config: UploaderConfig,
}

impl Shared {
    fn token(&self) -> String {
        self.token
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    fn set_state(&self, state: UploadState) {
        self.state.send_if_modified(|current| {
            // Closed and Stopped are final.
            if matches!(current, UploadState::Closed | UploadState::Stopped) || *current == state {
                return false;
            }
            *current = state;
            true
        });
    }

    fn close(&self) {
        self.set_state(UploadState::Closed);
        let _ = self.stop.send(true);
    }

    /// Adds the server's `missing` numbers that the queue still holds.
    fn want_resend(&self, missing: &[u64]) {
        if missing.is_empty() {
            return;
        }
        let held: Vec<u64> = self
            .queue
            .events(missing)
            .into_iter()
            .map(|e| e.seq)
            .collect();
        if held.is_empty() {
            return;
        }
        self.resend
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .extend(held);
        self.queue.appended().notify_one();
    }
}

/// Starts the upload and heartbeat loops.
#[derive(Debug)]
pub struct Uploader;

impl Uploader {
    /// Spawns the two loops on the current Tokio runtime (`tauri::async_runtime` in the app).
    ///
    /// - **Events:** whatever the queue holds above `acked_through`, plus what the server lists
    ///   as missing, in batches of at most `batch_max_events`, in `seq` order.
    /// - **Heartbeat:** every `heartbeat_interval`, with `seq_high` and `status()`.
    /// - **Failures** back off exponentially with jitter (honouring `Retry-After`).
    ///   `409 proctor-session-closed` stops both loops for good.
    pub fn spawn<A: ApiSource>(
        api: Arc<A>,
        queue: Arc<EventQueue>,
        proctor_session_id: String,
        session_token: String,
        status: Arc<dyn Fn() -> DeviceStatus + Send + Sync>,
        config: UploaderConfig,
    ) -> UploaderHandle {
        let (state, _) = watch::channel(UploadState::Idle);
        let (stop, _) = watch::channel(false);
        let shared = Arc::new(Shared {
            api,
            queue,
            session: proctor_session_id,
            token: Mutex::new(session_token),
            resend: Mutex::new(BTreeSet::new()),
            state,
            stop,
            status,
            config,
        });
        let tasks = vec![
            tokio::spawn(events_loop(shared.clone())),
            tokio::spawn(heartbeat_loop(shared.clone())),
        ];
        UploaderHandle { shared, tasks }
    }
}

/// The running uploader.
#[derive(Debug)]
pub struct UploaderHandle {
    shared: Arc<Shared>,
    tasks: Vec<JoinHandle<()>>,
}

impl std::fmt::Debug for Shared {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Shared")
            .field("session", &self.session)
            .field("state", &*self.state.borrow())
            .finish_non_exhaustive()
    }
}

impl UploaderHandle {
    /// Replaces the interview-session token (after the app obtained a new one).
    pub fn set_token(&self, token: String) {
        *self
            .shared
            .token
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = token;
        self.shared.queue.appended().notify_one();
    }

    pub fn state(&self) -> UploadState {
        self.shared.state.borrow().clone()
    }

    /// Follows state changes.
    pub fn subscribe(&self) -> watch::Receiver<UploadState> {
        self.shared.state.subscribe()
    }

    /// Waits until everything appended so far is acknowledged (`true`), the session closed or
    /// `timeout` passed (`false`).
    pub async fn flush(&self, timeout: Duration) -> bool {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            match self.state() {
                UploadState::Idle if self.shared.queue.is_drained() => return true,
                UploadState::Closed | UploadState::Stopped => {
                    return self.shared.queue.is_drained();
                }
                _ => {}
            }
            if tokio::time::Instant::now() >= deadline {
                return false;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }

    /// Whether both loops have ended (after a stop or a closed session).
    pub fn is_finished(&self) -> bool {
        self.tasks.iter().all(JoinHandle::is_finished)
    }

    /// Stops both loops and waits for them. Unsent events stay in the queue for next time.
    pub async fn stop(self) {
        self.shared.set_state(UploadState::Stopped);
        let _ = self.shared.stop.send(true);
        for task in self.tasks {
            let _ = task.await;
        }
    }
}

#[derive(Serialize)]
struct EventsBody<'a> {
    proctor_session_id: &'a str,
    events: &'a [ProctorEvent],
}

#[derive(Deserialize)]
struct EventsAck {
    acked_through: u64,
    #[serde(default)]
    missing: Vec<u64>,
}

#[derive(Serialize)]
struct HeartbeatBody<'a> {
    proctor_session_id: &'a str,
    seq_high: u64,
    #[serde(flatten)]
    status: DeviceStatus,
}

#[derive(Deserialize)]
struct HeartbeatAck {
    #[serde(default)]
    missing: Vec<u64>,
}

/// Waits for `period`; `true` when stopped meanwhile.
async fn sleep_or_stop(stop: &mut watch::Receiver<bool>, period: Duration) -> bool {
    if *stop.borrow() {
        return true;
    }
    tokio::select! {
        () = tokio::time::sleep(period) => *stop.borrow(),
        _ = stop.changed() => true,
    }
}

async fn events_loop(shared: Arc<Shared>) {
    let mut stop = shared.stop.subscribe();
    let appended = shared.queue.appended();
    let batch_max = shared.config.batch_max_events.max(1);
    let mut sent_through = shared.queue.acked_through();
    let mut attempt = 0u32;
    loop {
        if *stop.borrow() {
            return;
        }
        let acked = shared.queue.acked_through();
        sent_through = sent_through.max(acked);
        let resend: Vec<u64> = {
            let mut wanted = shared.resend.lock().unwrap_or_else(PoisonError::into_inner);
            let mut taken = Vec::new();
            while taken.len() < batch_max
                && let Some(seq) = wanted.pop_first()
            {
                if seq > acked {
                    taken.push(seq);
                }
            }
            taken
        };
        let mut batch = shared.queue.events(&resend);
        let room = batch_max - batch.len();
        batch.extend(shared.queue.pending(sent_through, room));
        batch.sort_by_key(|e| e.seq);
        batch.dedup_by_key(|e| e.seq);

        if batch.is_empty() {
            shared.set_state(UploadState::Idle);
            tokio::select! {
                () = appended.notified() => {}
                _ = stop.changed() => return,
            }
            continue;
        }
        if attempt == 0 {
            shared.set_state(UploadState::Sending);
        }
        let token = shared.token();
        let body = EventsBody {
            proctor_session_id: &shared.session,
            events: &batch,
        };
        let sent = tokio::select! {
            sent = shared.api.api().send::<_, EventsAck>(Method::POST, "proctoring/events", Some(&body), Some(&token)) => sent,
            _ = stop.changed() => return,
        };
        match sent {
            Ok(ack) => {
                attempt = 0;
                // A failure to persist the mark only means a few duplicates after a restart.
                let _ = shared.queue.record_ack(ack.acked_through);
                let highest = batch.last().map_or(0, |e| e.seq);
                sent_through = sent_through.max(highest);
                if ack.missing.is_empty() && ack.acked_through < sent_through {
                    // The server kept less than we sent and names no gap: send the rest again.
                    sent_through = ack.acked_through;
                }
                shared.want_resend(&ack.missing);
            }
            Err(error) if error.is_problem(SESSION_CLOSED) => {
                shared.close();
                return;
            }
            Err(error) => {
                attempt = attempt.saturating_add(1);
                shared
                    .resend
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .extend(resend);
                shared.set_state(UploadState::Retrying {
                    code: error.code().to_owned(),
                    attempt,
                });
                let delay = backoff(&shared.config, attempt, error.retry_after());
                if sleep_or_stop(&mut stop, delay).await {
                    return;
                }
            }
        }
    }
}

async fn heartbeat_loop(shared: Arc<Shared>) {
    let mut stop = shared.stop.subscribe();
    let mut ticks = tokio::time::interval(shared.config.heartbeat_interval);
    ticks.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    loop {
        tokio::select! {
            _ = ticks.tick() => {}
            _ = stop.changed() => return,
        }
        if *stop.borrow() {
            return;
        }
        let token = shared.token();
        let body = HeartbeatBody {
            proctor_session_id: &shared.session,
            seq_high: shared.queue.seq_high(),
            status: (shared.status)(),
        };
        let sent = tokio::select! {
            sent = shared.api.api().send::<_, HeartbeatAck>(Method::POST, "proctoring/heartbeat", Some(&body), Some(&token)) => sent,
            _ = stop.changed() => return,
        };
        match sent {
            Ok(ack) => shared.want_resend(&ack.missing),
            Err(error) if error.is_problem(SESSION_CLOSED) => {
                shared.close();
                return;
            }
            // The next tick tries again; the server notices missed heartbeats on its own.
            Err(_) => {}
        }
    }
}

/// Exponential backoff with jitter: half the step fixed, half random. A `Retry-After` from
/// the server wins when longer, up to `retry_after_max`.
fn backoff(config: &UploaderConfig, attempt: u32, retry_after: Option<u64>) -> Duration {
    let exponent = attempt.saturating_sub(1).min(20);
    let step = config
        .backoff_base
        .saturating_mul(1u32 << exponent)
        .min(config.backoff_max);
    let half = step / 2;
    let jitter = half.mul_f64(fastrand::f64());
    let delay = half + jitter;
    match retry_after {
        Some(seconds) => delay.max(Duration::from_secs(seconds).min(config.retry_after_max)),
        None => delay,
    }
}

#[cfg(test)]
mod tests {
    use super::HeartbeatAck;

    #[test]
    fn a_heartbeat_answer_with_snapshot_requests_still_reads() {
        // The server (SP-14) may ask for evidence pictures in the heartbeat answer; answering
        // them is still open (PENDING_TASKS B3), but the new field must not break the reader.
        let answer = r#"{ "acked_through": 41, "missing": [42, 44],
            "snapshot_requests": [{ "request_id": "r1", "event_id": "e1", "kind": "screen",
                                    "requested_at": "2026-10-12T05:01:02.120Z" }] }"#;
        let ack: HeartbeatAck = serde_json::from_str(answer).expect("an answer");
        assert_eq!(ack.missing, [42, 44]);
    }
}
