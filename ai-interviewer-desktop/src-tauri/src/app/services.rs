//! The services that run while an interview is on (SP-08b part 2): native monitoring and the
//! proctoring queue (SP-11), the recordings (SP-12) and the upload that follows. The webview
//! starts them with `services_start` once it has joined, and ends them with `services_stop`.
//!
//! ```text
//!   start:  proctor session ─▶ EventQueue ─▶ event uploader (+ heartbeats)
//!                                 ▲
//!           Monitor ─▶ pump thread ─▶ DeviceRules      webview face events ─┘
//!           screen Recorder ─▶ SegmentStore ◀─ webview camera/mic segments
//!                                   └──▶ recording uploader (run) ─▶ drain after stop
//! ```
//!
//! Nothing here holds a token for the webview: the session token comes from the app's cache
//! and goes straight into the uploaders.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
#[cfg(windows)]
use std::sync::Weak;
use std::sync::mpsc::{Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::thread::JoinHandle as ThreadHandle;
use std::time::{Duration, Instant};

use hv_api_client::{ApiClient, SessionManager};
use hv_event_queue::{
    DeviceRules, DeviceStatus, EventDraft, EventName, EventQueue, SessionPolicy, Source,
    UploadState, UploaderConfig as EventUploaderConfig, UploaderHandle, open_session,
};
use hv_monitor::{Clock, Monitor, MonitorConfig, MonitorHandle, Observation};
use hv_security::Vault;
use hv_segment_store::webview::segment_from_headers;
use hv_segment_store::{Codec, Container, NewSegment, SegmentStore, StoreError, Track};
use hv_uploader::{
    RecordingSession, TokenFuture, UploadEvent, Uploader as RecordingUploader,
    UploaderConfig as RecordingUploaderConfig,
};
use serde::Serialize;
use serde_json::{Value, json};
use tokio::sync::{broadcast, watch};

use super::error::{CommandError, CommandResult};
use super::interview::{SessionTokens, check_interview_id, session_token};
use super::proctoring::{FaceEvent, StatusSnapshot, device_label, heartbeat_status};
use super::progress::UploadProgress;

/// Sent to the webview when the server won't take a camera or microphone track
/// (`track-not-recorded`); the payload is the track name. The webview stops recording it.
pub const TRACK_REFUSED_EVENT: &str = "hv:track-refused";
/// Sent to the webview when the services stop: stop recording the camera and microphone.
pub const STOP_MEDIA_EVENT: &str = "hv:stop-media";

/// Sends an event to the webview.
pub type Notify = Arc<dyn Fn(&str, Value) + Send + Sync>;

/// How long the last events get to reach the server when the interview ends.
const FLUSH_ON_COMPLETE: Duration = Duration::from_secs(5);
const FLUSH_ON_EXIT: Duration = Duration::from_secs(1);

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Why the services are stopping.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StopMode {
    /// The interview ended: upload what's left, in the background, until the server has it.
    Complete,
    /// The app is closing: keep everything on disk for the next launch.
    Exit,
}

/// What `services_start` tells the webview.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct ServicesStarted {
    /// The proctor session is open and events are being queued.
    pub proctoring: bool,
    /// The native watchers are running.
    pub monitoring: bool,
    /// Recording (the store and the uploader) is ready for camera and microphone segments.
    pub recording: bool,
    /// The screen is being recorded.
    pub screen: bool,
    /// The parts of the proctor policy the on-device camera analysis uses
    /// (`thresholds`, `accommodations`).
    pub policy: Option<Value>,
    /// Parts that didn't start, so the webview can try again.
    pub problems: Vec<Problem>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Problem {
    pub part: &'static str,
    pub code: String,
}

impl Problem {
    fn new(part: &'static str, error: &CommandError) -> Self {
        Self {
            part,
            code: error.code.clone(),
        }
    }
}

/// What `recording_store_segment` answers.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct StoredSegmentView {
    pub track: String,
    pub seq: u64,
    pub bytes: u64,
    pub state: String,
}

// ---------------------------------------------------------------------------------------------
// Proctoring

/// The proctor session as the rest of the app sees it.
pub(super) struct ProctoringShared {
    queue: Arc<EventQueue>,
    rules: Mutex<DeviceRules>,
    status: Mutex<StatusSnapshot>,
}

impl ProctoringShared {
    fn new(queue: Arc<EventQueue>, rules: DeviceRules) -> Self {
        Self {
            queue,
            rules: Mutex::new(rules),
            status: Mutex::new(StatusSnapshot::default()),
        }
    }

    fn append(&self, drafts: Vec<EventDraft>) {
        if drafts.is_empty() {
            return;
        }
        if let Err(error) = self.queue.append_all(drafts) {
            eprintln!("proctoring: an event couldn't be queued: {error}");
        }
    }

    /// Turns one monitor observation into queued events and keeps the display count.
    fn observe(&self, observation: &Observation) {
        if let Observation::DisplayChanged(change) = observation {
            lock(&self.status).displays = u32::try_from(change.display_count).unwrap_or(u32::MAX);
        }
        let drafts = lock(&self.rules).observe(observation);
        self.append(drafts);
    }

    fn tick(&self, now_ms: i64) {
        let drafts = lock(&self.rules).tick(now_ms);
        self.append(drafts);
    }

    fn finish(&self, now_ms: i64) {
        let drafts = lock(&self.rules).finish(now_ms);
        self.append(drafts);
    }

    /// Queues a camera event from the webview's face module; returns its `seq`.
    fn enqueue(&self, event: FaceEvent) -> CommandResult<u64> {
        let draft = event.into_draft()?;
        self.queue
            .append(draft)
            .map(|queued| queued.seq)
            .map_err(|error| CommandError::new("proctoring-storage", error.to_string()))
    }

    /// The camera and microphone the interview uses: `None` is "not capturing".
    fn set_devices(&self, camera: Option<String>, mic: Option<String>) -> CommandResult<()> {
        let camera_label = device_label(camera.as_deref())?;
        let mic_label = device_label(mic.as_deref())?;
        // An unnamed device is in use but can't narrow the disconnect rules.
        let named = |label: &Option<String>| label.clone().filter(|name| !name.is_empty());
        lock(&self.rules).set_active_devices(named(&camera_label), named(&mic_label));
        let mut status = lock(&self.status);
        status.camera_on = camera_label.is_some();
        status.mic_on = mic_label.is_some();
        Ok(())
    }

    fn device_status(&self) -> DeviceStatus {
        heartbeat_status(&lock(&self.status))
    }

    fn set_screen_capturing(&self, capturing: bool, displays: Option<u32>) {
        let mut status = lock(&self.status);
        status.screen_capturing = capturing;
        if let Some(displays) = displays {
            status.displays = displays;
        }
    }
}

/// Deletes a finished proctor session's queue, once nothing else holds it.
fn purge(shared: Arc<ProctoringShared>) {
    let Ok(shared) = Arc::try_unwrap(shared) else {
        eprintln!("proctoring: the queue is still in use, so it stays on disk");
        return;
    };
    match Arc::try_unwrap(shared.queue) {
        Ok(queue) => {
            if let Err(error) = queue.purge() {
                eprintln!("proctoring: the queue couldn't be deleted: {error}");
            }
        }
        Err(_) => eprintln!("proctoring: the queue is still in use, so it stays on disk"),
    }
}

/// The monitor's observations into the queue: one thread, so the rules see them in order.
fn spawn_pump(
    shared: Arc<ProctoringShared>,
    observations: Receiver<Observation>,
    clock: Clock,
) -> std::io::Result<ThreadHandle<()>> {
    std::thread::Builder::new()
        .name("hv-event-pump".into())
        .spawn(move || {
            let mut last_tick = Instant::now();
            loop {
                match observations.recv_timeout(Duration::from_secs(1)) {
                    Ok(observation) => shared.observe(&observation),
                    Err(RecvTimeoutError::Timeout) => {}
                    // Every watcher has stopped.
                    Err(RecvTimeoutError::Disconnected) => break,
                }
                if last_tick.elapsed() >= Duration::from_secs(1) {
                    shared.tick(clock());
                    last_tick = Instant::now();
                }
            }
        })
}

struct ProctoringRun {
    shared: Arc<ProctoringShared>,
    policy: Value,
    uploader: Arc<UploaderHandle>,
    watcher: tauri::async_runtime::JoinHandle<()>,
    monitor: Option<(MonitorHandle, ThreadHandle<()>)>,
    clock: Clock,
}

impl ProctoringRun {
    /// Stops the watchers, closes the open periods, sends what's left (unless the server
    /// closed the session) and stops the uploader. Returns the queue and whether it can go.
    async fn shutdown(self, mode: StopMode, session_closed: bool) -> (Arc<ProctoringShared>, bool) {
        let Self {
            shared,
            uploader,
            watcher,
            monitor,
            clock,
            ..
        } = self;
        watcher.abort();
        let _ = watcher.await;
        if let Some((handle, pump)) = monitor {
            // Stopping joins the watcher threads; the pump ends when its channel closes.
            let _ = tauri::async_runtime::spawn_blocking(move || {
                handle.stop();
                let _ = pump.join();
            })
            .await;
        }
        let mut delivered = false;
        if !session_closed {
            shared.finish(clock());
            let wait = if mode == StopMode::Exit {
                FLUSH_ON_EXIT
            } else {
                FLUSH_ON_COMPLETE
            };
            delivered = uploader.flush(wait).await;
        }
        stop_event_uploader(uploader).await;
        (shared, session_closed || delivered)
    }
}

/// `UploaderHandle::stop` consumes the handle, which the watcher shared until it was aborted.
async fn stop_event_uploader(mut handle: Arc<UploaderHandle>) {
    for _ in 0..50 {
        match Arc::try_unwrap(handle) {
            Ok(handle) => {
                handle.stop().await;
                return;
            }
            Err(shared) => {
                handle = shared;
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Recording

/// Lets the uploader sign calls with the app's client and the interview's session token.
struct InterviewSession {
    session: Arc<SessionManager>,
    tokens: Arc<SessionTokens>,
    interview_id: String,
}

impl RecordingSession for InterviewSession {
    fn api(&self) -> &ApiClient {
        self.session.api()
    }

    fn token(&self) -> TokenFuture<'_> {
        Box::pin(
            async move { session_token(&self.session, &self.tokens, &self.interview_id).await },
        )
    }
}

/// Where the webview's camera and microphone segments go while an interview records.
pub(super) struct RecordingIntake {
    interview_id: String,
    store: Arc<SegmentStore>,
    /// Wakes the uploader after a segment is stored.
    wake: Arc<dyn Fn() + Send + Sync>,
}

impl RecordingIntake {
    /// Stores one segment the webview described with headers. The interview comes from here,
    /// never from the webview.
    async fn store(
        &self,
        header: impl Fn(&str) -> Option<String>,
        bytes: &[u8],
    ) -> CommandResult<StoredSegmentView> {
        let new = segment_from_headers(&self.interview_id, header).map_err(store_error)?;
        let store = self.store.clone();
        let plain = bytes.to_vec();
        let stored = tauri::async_runtime::spawn_blocking(move || store.put(new, &plain))
            .await
            .map_err(|error| CommandError::new("storage-failed", error.to_string()))?
            .map_err(store_error)?;
        (self.wake)();
        Ok(StoredSegmentView {
            track: stored.track.to_string(),
            seq: stored.seq,
            bytes: stored.bytes,
            state: stored.state.to_string(),
        })
    }
}

fn store_error(error: StoreError) -> CommandError {
    match error {
        StoreError::Contract(why) => CommandError::new("invalid-segment", why),
        StoreError::Conflict(why) => CommandError::new("segment-conflict", why),
        other => CommandError::new("storage-failed", other.to_string()),
    }
}

/// A screen segment from the native recorder as the store takes it, or why it can't be.
pub(super) fn screen_segment(
    interview_id: &str,
    track: &str,
    seq: u64,
    started_at_ms: i64,
    duration_ms: u32,
) -> Result<NewSegment, String> {
    let track: Track = track.parse()?;
    if !track.is_screen() {
        return Err(format!("{track} isn't a screen track"));
    }
    Ok(NewSegment {
        interview_id: interview_id.to_owned(),
        track,
        seq,
        started_at_ms,
        duration_ms: duration_ms.max(1),
        container: Container::Mp4,
        codec: Codec::H264,
    })
}

/// `SCREEN_CAPTURE_STOPPED`: a display stopped recording.
pub(super) fn screen_stopped(track: &str, why: &str, now_ms: i64) -> EventDraft {
    EventDraft::new(EventName::ScreenCaptureStopped, Source::Screen, now_ms)
        .details(json!({ "track": track, "reason": why }))
}

/// What the app does about an upload event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum Reaction {
    /// Tell the webview to stop recording this camera or microphone track.
    StopTrack(String),
    /// The cached session token was rejected; fetch a new one.
    ForgetToken,
    Nothing,
}

pub(super) fn react_to(event: &UploadEvent) -> Reaction {
    match event {
        UploadEvent::TrackRefused { track } if !track.is_screen() => {
            Reaction::StopTrack(track.to_string())
        }
        UploadEvent::Retrying { code, .. } if code == "token-invalid" => Reaction::ForgetToken,
        _ => Reaction::Nothing,
    }
}

fn spawn_upload_watcher(
    mut events: broadcast::Receiver<UploadEvent>,
    tokens: Arc<SessionTokens>,
    interview_id: String,
    notify: Notify,
) -> tauri::async_runtime::JoinHandle<()> {
    tauri::async_runtime::spawn(async move {
        loop {
            match events.recv().await {
                Ok(event) => match react_to(&event) {
                    Reaction::StopTrack(track) => notify(TRACK_REFUSED_EVENT, json!(track)),
                    Reaction::ForgetToken => tokens.forget(&interview_id),
                    Reaction::Nothing => {}
                },
                Err(broadcast::error::RecvError::Lagged(_)) => {}
                Err(broadcast::error::RecvError::Closed) => break,
            }
        }
    })
}

/// Stores each finished screen segment, encrypted, and wakes the uploader.
#[cfg(windows)]
struct ScreenSink {
    interview_id: String,
    store: Arc<SegmentStore>,
    wake: Arc<dyn Fn() + Send + Sync>,
    proctoring: Weak<ProctoringShared>,
    clock: Clock,
}

#[cfg(windows)]
impl hv_recorder::recorder::SegmentSink for ScreenSink {
    fn segment(&self, segment: hv_recorder::recorder::RecordedSegment) {
        // This runs on the recorder's finalizer thread, which `Recorder::stop` joins, so the
        // last segment is durable by the time the screen recorder has stopped.
        let new = match screen_segment(
            &self.interview_id,
            &segment.track,
            segment.seq,
            segment.started_at_ms,
            segment.duration_ms,
        ) {
            Ok(new) => new,
            Err(why) => {
                eprintln!("recording: a screen segment was dropped: {why}");
                return;
            }
        };
        match self.store.put(new, &segment.bytes) {
            Ok(_) => (self.wake)(),
            Err(error) => eprintln!(
                "recording: {} segment {} couldn't be stored: {error}",
                segment.track, segment.seq
            ),
        }
    }

    fn display_failed(&self, track: &str, error: &str) {
        eprintln!("recording: {track} stopped: {error}");
        if let Some(shared) = self.proctoring.upgrade() {
            shared.set_screen_capturing(false, None);
            shared.append(vec![screen_stopped(
                track,
                "capture_failed",
                (self.clock)(),
            )]);
        }
    }
}

struct RecordingRun {
    uploader: Arc<RecordingUploader>,
    stop: watch::Sender<bool>,
    run: tauri::async_runtime::JoinHandle<()>,
    watcher: tauri::async_runtime::JoinHandle<()>,
    #[cfg(windows)]
    screen: Option<hv_recorder::recorder::Recorder>,
}

impl RecordingRun {
    fn recording_screen(&self) -> bool {
        #[cfg(windows)]
        {
            self.screen.is_some()
        }
        #[cfg(not(windows))]
        {
            false
        }
    }
}

// ---------------------------------------------------------------------------------------------
// The service

struct Live {
    version: String,
    session: Arc<SessionManager>,
    tokens: Arc<SessionTokens>,
    /// `None` when the store couldn't be opened: recording is then unavailable.
    store: Option<Arc<SegmentStore>>,
    proctoring_root: PathBuf,
}

struct Active {
    interview_id: String,
    notify: Notify,
    proctoring: Option<ProctoringRun>,
    recording: Option<RecordingRun>,
}

impl Active {
    fn view(&self) -> ServicesStarted {
        ServicesStarted {
            proctoring: self.proctoring.is_some(),
            monitoring: self
                .proctoring
                .as_ref()
                .is_some_and(|run| run.monitor.is_some()),
            recording: self.recording.is_some(),
            screen: self
                .recording
                .as_ref()
                .is_some_and(RecordingRun::recording_screen),
            policy: self.proctoring.as_ref().map(|run| run.policy.clone()),
            problems: Vec::new(),
        }
    }
}

struct Inner {
    live: Option<Live>,
    /// Held while starting or stopping, so two calls (React runs effects twice in development)
    /// can't start two of everything.
    active: tokio::sync::Mutex<Option<Active>>,
    /// The hot paths (face events, segments) don't wait for `active`.
    proctoring: Mutex<Option<Arc<ProctoringShared>>>,
    recording: Mutex<Option<Arc<RecordingIntake>>>,
    /// Interviews whose leftover segments are uploading.
    draining: Mutex<HashSet<String>>,
    /// Ends every background upload (sign-out, exit). Replaced by a fresh channel when it fires,
    /// so uploads started afterwards aren't born stopped.
    background_stop: Mutex<watch::Sender<bool>>,
}

/// The interview services. Cheap to clone.
#[derive(Clone)]
pub struct Services {
    inner: Arc<Inner>,
}

impl Services {
    fn with(live: Option<Live>) -> Self {
        Self {
            inner: Arc::new(Inner {
                live,
                active: tokio::sync::Mutex::new(None),
                proctoring: Mutex::new(None),
                recording: Mutex::new(None),
                draining: Mutex::new(HashSet::new()),
                background_stop: Mutex::new(watch::channel(false).0),
            }),
        }
    }

    /// For the stub: every call succeeds and nothing starts.
    pub fn disabled() -> Self {
        Self::with(None)
    }

    /// Opens the segment store (and logs what a crash left behind to repair).
    pub fn live(
        version: &str,
        data_dir: &Path,
        session: Arc<SessionManager>,
        tokens: Arc<SessionTokens>,
    ) -> Self {
        let store = match SegmentStore::open(
            data_dir.join("recordings"),
            Vault::new(data_dir.join("vault")),
        ) {
            Ok((store, recovery)) => {
                if recovery != hv_segment_store::Recovery::default() {
                    eprintln!("recording: the store recovered after a crash: {recovery:?}");
                }
                Some(Arc::new(store))
            }
            Err(error) => {
                eprintln!("recording: the segment store couldn't be opened: {error}");
                None
            }
        };
        Self::with(Some(Live {
            version: version.to_owned(),
            session,
            tokens,
            store,
            proctoring_root: data_dir.join("proctoring"),
        }))
    }

    /// Starts whatever isn't running yet for `interview_id`: the proctor session with its
    /// monitor, and recording. Safe to call again (it fills in what failed before).
    pub async fn start(
        &self,
        notify: Notify,
        interview_id: &str,
        startup_integrity: Vec<(String, Option<String>)>,
    ) -> CommandResult<ServicesStarted> {
        check_interview_id(interview_id)?;
        let Some(live) = self.inner.live.as_ref() else {
            return Ok(ServicesStarted::default());
        };
        let mut guard = self.inner.active.lock().await;
        if guard
            .as_ref()
            .is_some_and(|active| active.interview_id != interview_id)
        {
            return Err(CommandError::new("services-busy", None));
        }
        let token = session_token(&live.session, &live.tokens, interview_id).await?;
        let active = guard.get_or_insert_with(|| Active {
            interview_id: interview_id.to_owned(),
            notify: notify.clone(),
            proctoring: None,
            recording: None,
        });
        active.notify = notify;
        let mut problems = Vec::new();

        if active.proctoring.is_none() {
            match self
                .start_proctoring(live, interview_id, &token, startup_integrity)
                .await
            {
                Ok(run) => {
                    *lock(&self.inner.proctoring) = Some(run.shared.clone());
                    active.proctoring = Some(run);
                }
                Err(error) => problems.push(Problem::new("proctoring", &error)),
            }
        }
        if active.recording.is_none() {
            let shared = active.proctoring.as_ref().map(|run| run.shared.clone());
            match self
                .start_recording(live, interview_id, active.notify.clone(), shared)
                .await
            {
                Ok(run) => active.recording = Some(run),
                Err(error) => problems.push(Problem::new("recording", &error)),
            }
        }
        let mut view = active.view();
        view.problems = problems;
        Ok(view)
    }

    async fn start_proctoring(
        &self,
        live: &Live,
        interview_id: &str,
        token: &str,
        startup_integrity: Vec<(String, Option<String>)>,
    ) -> CommandResult<ProctoringRun> {
        let policy: SessionPolicy =
            open_session(live.session.api(), token, interview_id, &live.version).await?;
        let queue = EventQueue::open(&live.proctoring_root, &policy.proctor_session_id)
            .map_err(|error| CommandError::new("proctoring-storage", error.to_string()))?;
        if let Some(acked_through) = policy.acked_through
            && let Err(error) = queue.record_ack(acked_through)
        {
            eprintln!("proctoring: the server's acknowledgement couldn't be saved: {error}");
        }
        let shared = Arc::new(ProctoringShared::new(
            Arc::new(queue),
            DeviceRules::from_policy(&policy),
        ));

        let status = {
            let shared = shared.clone();
            Arc::new(move || shared.device_status())
        };
        let uploader = Arc::new(hv_event_queue::Uploader::spawn(
            live.session.clone(),
            shared.queue.clone(),
            policy.proctor_session_id.clone(),
            token.to_owned(),
            status,
            EventUploaderConfig::from_policy(&policy),
        ));

        let clock: Clock = {
            let session = live.session.clone();
            Arc::new(move || session.api().server_now_ms())
        };
        let config = MonitorConfig {
            watch: policy.monitor_watch(),
            clock: clock.clone(),
            startup_integrity,
            ..MonitorConfig::default()
        };
        let monitor = match Monitor::start(config) {
            Ok((handle, observations)) => {
                match spawn_pump(shared.clone(), observations, clock.clone()) {
                    Ok(pump) => Some((handle, pump)),
                    Err(error) => {
                        eprintln!("proctoring: the event pump couldn't start: {error}");
                        handle.stop();
                        None
                    }
                }
            }
            Err(error) => {
                eprintln!("proctoring: native monitoring couldn't start: {error}");
                None
            }
        };

        let watcher = self.spawn_session_watcher(live, interview_id, uploader.clone());
        Ok(ProctoringRun {
            shared,
            policy: json!({
                "thresholds": policy.thresholds,
                "accommodations": policy.accommodations,
            }),
            uploader,
            watcher,
            monitor,
            clock,
        })
    }

    /// Follows the event uploader: a rejected session token is replaced, and a closed proctor
    /// session (409) ends the monitoring.
    fn spawn_session_watcher(
        &self,
        live: &Live,
        interview_id: &str,
        uploader: Arc<UploaderHandle>,
    ) -> tauri::async_runtime::JoinHandle<()> {
        let services = self.clone();
        let session = live.session.clone();
        let tokens = live.tokens.clone();
        let interview_id = interview_id.to_owned();
        let mut state = uploader.subscribe();
        tauri::async_runtime::spawn(async move {
            while state.changed().await.is_ok() {
                let current = state.borrow_and_update().clone();
                match current {
                    UploadState::Closed => {
                        // Not awaited here: shutting down aborts this very task.
                        tauri::async_runtime::spawn(async move {
                            services.proctoring_closed().await;
                        });
                        return;
                    }
                    UploadState::Retrying { code, .. } if code == "token-invalid" => {
                        tokens.forget(&interview_id);
                        if let Ok(token) = session_token(&session, &tokens, &interview_id).await {
                            uploader.set_token(token);
                        }
                    }
                    _ => {}
                }
            }
        })
    }

    /// The server closed the proctor session (the interview completed): stop watching and
    /// delete the queue.
    async fn proctoring_closed(&self) {
        let mut guard = self.inner.active.lock().await;
        let Some(run) = guard.as_mut().and_then(|active| active.proctoring.take()) else {
            return;
        };
        *lock(&self.inner.proctoring) = None;
        let (shared, _) = run.shutdown(StopMode::Complete, true).await;
        purge(shared);
    }

    async fn start_recording(
        &self,
        live: &Live,
        interview_id: &str,
        notify: Notify,
        proctoring: Option<Arc<ProctoringShared>>,
    ) -> CommandResult<RecordingRun> {
        let store = live
            .store
            .clone()
            .ok_or_else(|| CommandError::new("recording-unavailable", None))?;
        let session = Arc::new(InterviewSession {
            session: live.session.clone(),
            tokens: live.tokens.clone(),
            interview_id: interview_id.to_owned(),
        });
        let uploader = Arc::new(
            RecordingUploader::new(session, store.clone(), RecordingUploaderConfig::default())
                .map_err(|error| CommandError::new("recording-unavailable", error.to_string()))?,
        );
        let wake: Arc<dyn Fn() + Send + Sync> = {
            let uploader = uploader.clone();
            Arc::new(move || uploader.wake())
        };

        // Subscribe before the loop starts, so no event is missed.
        let watcher = spawn_upload_watcher(
            uploader.subscribe(),
            live.tokens.clone(),
            interview_id.to_owned(),
            notify,
        );
        let (stop, stop_receiver) = watch::channel(false);
        let run = {
            let uploader = uploader.clone();
            let interview_id = interview_id.to_owned();
            tauri::async_runtime::spawn(async move {
                if let Err(error) = uploader.run(&interview_id, stop_receiver).await {
                    eprintln!("recording: the uploader stopped: {error}");
                }
            })
        };

        #[cfg(windows)]
        let screen = self
            .start_screen(
                live,
                interview_id,
                &store,
                wake.clone(),
                proctoring.as_ref(),
            )
            .await;
        #[cfg(not(windows))]
        let _ = &proctoring;

        *lock(&self.inner.recording) = Some(Arc::new(RecordingIntake {
            interview_id: interview_id.to_owned(),
            store,
            wake,
        }));
        Ok(RecordingRun {
            uploader,
            stop,
            run,
            watcher,
            #[cfg(windows)]
            screen,
        })
    }

    /// Starts recording every display. A failure is reported as `SCREEN_CAPTURE_STOPPED`; the
    /// camera and microphone still record.
    #[cfg(windows)]
    async fn start_screen(
        &self,
        live: &Live,
        interview_id: &str,
        store: &Arc<SegmentStore>,
        wake: Arc<dyn Fn() + Send + Sync>,
        proctoring: Option<&Arc<ProctoringShared>>,
    ) -> Option<hv_recorder::recorder::Recorder> {
        let clock: Clock = {
            let session = live.session.clone();
            Arc::new(move || session.api().server_now_ms())
        };
        let sink = Arc::new(ScreenSink {
            interview_id: interview_id.to_owned(),
            store: store.clone(),
            wake,
            proctoring: proctoring.map_or_else(Weak::new, Arc::downgrade),
            clock: clock.clone(),
        });
        let started = tauri::async_runtime::spawn_blocking(move || {
            hv_recorder::recorder::Recorder::start(
                hv_recorder::recorder::RecorderConfig::default(),
                sink,
                clock,
            )
            .map_err(|error| error.to_string())
        })
        .await;
        let failure = match started {
            Ok(Ok(recorder)) => {
                if let Some(shared) = proctoring {
                    let displays = u32::try_from(recorder.tracks().len()).ok();
                    shared.set_screen_capturing(true, displays);
                }
                return Some(recorder);
            }
            Ok(Err(error)) => error,
            Err(error) => error.to_string(),
        };
        eprintln!("recording: the screen recorder couldn't start: {failure}");
        if let Some(shared) = proctoring {
            shared.set_screen_capturing(false, None);
            shared.append(vec![screen_stopped(
                "screen-1",
                "start_failed",
                live.session.api().server_now_ms(),
            )]);
        }
        None
    }

    /// Ends the services for the running interview: the monitor and the event queue first (so
    /// the last events go out while the proctor session is open), then the screen recorder.
    /// The remaining segments upload in the background; see [`Services::upload_progress`].
    pub async fn stop(&self, mode: StopMode) {
        let mut guard = self.inner.active.lock().await;
        let Some(active) = guard.take() else {
            return;
        };
        let Active {
            interview_id,
            notify,
            proctoring,
            recording,
        } = active;
        // The webview normally stopped its camera and microphone recording before asking.
        notify(STOP_MEDIA_EVENT, Value::Null);
        *lock(&self.inner.proctoring) = None;

        let mut remains = None;
        if let Some(run) = proctoring {
            remains = Some(run.shutdown(mode, false).await);
        }
        if let Some(run) = recording {
            self.stop_recording(&interview_id, run, mode).await;
        }
        if let Some((shared, true)) = remains {
            purge(shared);
        }
    }

    async fn stop_recording(&self, interview_id: &str, run: RecordingRun, mode: StopMode) {
        let RecordingRun {
            uploader,
            stop,
            run: loop_handle,
            watcher,
            #[cfg(windows)]
            screen,
        } = run;
        #[cfg(windows)]
        if let Some(recorder) = screen {
            // Joins the display threads: the last screen segments are stored when it returns.
            let _ = tauri::async_runtime::spawn_blocking(move || recorder.stop()).await;
        }
        let _ = stop.send(true);
        let _ = loop_handle.await;
        watcher.abort();
        let _ = watcher.await;
        // Late segments from the webview are refused from here on.
        *lock(&self.inner.recording) = None;
        if mode == StopMode::Complete {
            self.spawn_drain(interview_id, uploader);
        }
    }

    /// Uploads everything of `interview_id` that's still pending, then forgets its key.
    fn spawn_drain(&self, interview_id: &str, uploader: Arc<RecordingUploader>) {
        let Some(live) = self.inner.live.as_ref() else {
            return;
        };
        if !lock(&self.inner.draining).insert(interview_id.to_owned()) {
            return;
        }
        let inner = self.inner.clone();
        let store = live.store.clone();
        let tokens = live.tokens.clone();
        let interview_id = interview_id.to_owned();
        let mut stop = lock(&self.inner.background_stop).subscribe();
        tauri::async_runtime::spawn(async move {
            tokio::select! {
                result = uploader.drain(&interview_id) => match result {
                    Ok(()) => {
                        if let Some(store) = store {
                            match store.forget_interview(&interview_id) {
                                Ok(_) => tokens.forget(&interview_id),
                                Err(error) => eprintln!("recording: the key couldn't be dropped: {error}"),
                            }
                        }
                    }
                    Err(error) => eprintln!("recording: the upload stopped: {error}"),
                },
                _ = stop.wait_for(|stopped| *stopped) => {}
            }
            lock(&inner.draining).remove(&interview_id);
        });
    }

    /// After sign-in: uploads what an earlier run (a crash, a closed laptop) left behind.
    pub fn resume_pending(&self) {
        let Some(live) = self.inner.live.as_ref() else {
            return;
        };
        let Some(store) = live.store.as_ref() else {
            return;
        };
        let pending = match store.interviews_with_pending() {
            Ok(pending) => pending,
            Err(error) => {
                eprintln!("recording: the pending interviews couldn't be listed: {error}");
                return;
            }
        };
        let running = lock(&self.inner.recording)
            .as_ref()
            .map(|intake| intake.interview_id.clone());
        for interview_id in pending {
            if running.as_deref() == Some(interview_id.as_str()) {
                continue;
            }
            let session = Arc::new(InterviewSession {
                session: live.session.clone(),
                tokens: live.tokens.clone(),
                interview_id: interview_id.clone(),
            });
            match RecordingUploader::new(session, store.clone(), RecordingUploaderConfig::default())
            {
                Ok(uploader) => self.spawn_drain(&interview_id, Arc::new(uploader)),
                Err(error) => eprintln!("recording: the uploader couldn't be built: {error}"),
            }
        }
    }

    /// Ends the background uploads (sign-out). The segments stay on disk for the next sign-in.
    pub fn cancel_background(&self) {
        let fired = std::mem::replace(
            &mut *lock(&self.inner.background_stop),
            watch::channel(false).0,
        );
        let _ = fired.send(true);
    }

    pub fn enqueue_face_event(&self, event: FaceEvent) -> CommandResult<u64> {
        let shared = lock(&self.inner.proctoring)
            .clone()
            .ok_or_else(|| CommandError::new("proctoring-inactive", None))?;
        shared.enqueue(event)
    }

    /// The camera and microphone in use. Nothing to do while proctoring isn't running.
    pub fn set_devices(&self, camera: Option<String>, mic: Option<String>) -> CommandResult<()> {
        let shared = lock(&self.inner.proctoring).clone();
        match shared {
            Some(shared) => shared.set_devices(camera, mic),
            None => Ok(()),
        }
    }

    /// Server time minus this PC's time, for stamping camera and microphone segments.
    pub async fn clock_offset_ms(&self) -> i64 {
        let Some(live) = self.inner.live.as_ref() else {
            return 0;
        };
        let api = live.session.api();
        if api.clock().is_none() {
            let _ = api.sync_clock().await;
        }
        api.clock().map_or(0, |sample| sample.offset_ms)
    }

    /// Stores a camera or microphone segment from the webview.
    pub async fn store_segment(
        &self,
        header: impl Fn(&str) -> Option<String>,
        bytes: &[u8],
    ) -> CommandResult<StoredSegmentView> {
        let intake = lock(&self.inner.recording)
            .clone()
            .ok_or_else(|| CommandError::new("recording-inactive", None))?;
        intake.store(header, bytes).await
    }

    /// How much of an interview's recording the server has, for the drain screen.
    pub fn upload_progress(&self, interview_id: &str) -> CommandResult<UploadProgress> {
        check_interview_id(interview_id)?;
        let recording = lock(&self.inner.recording)
            .as_ref()
            .is_some_and(|intake| intake.interview_id == interview_id);
        let store = self
            .inner
            .live
            .as_ref()
            .and_then(|live| live.store.as_ref());
        let Some(store) = store else {
            return Ok(UploadProgress::nothing(recording));
        };
        let counts = store.counts(interview_id).map_err(store_error)?;
        Ok(UploadProgress::from_counts(&counts, recording))
    }

    /// When the app exits: stop everything quickly; what's pending uploads at the next launch.
    pub fn stop_for_exit(&self) {
        self.cancel_background();
        // `block_on` panics on a thread that already drives a runtime, and this is also called
        // from one (the updater's before-exit hook), so wait for the stop on a thread of its own.
        std::thread::scope(|scope| {
            let _ = scope
                .spawn(|| tauri::async_runtime::block_on(self.stop(StopMode::Exit)))
                .join();
        });
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use hv_segment_store::SegmentState;
    use serde_json::json;

    use super::*;

    const INTERVIEW: &str = "0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6";

    /// A fresh directory under the system temp dir, removed on drop.
    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let dir = std::env::temp_dir().join(format!(
                "hv-app-test-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir_all(&dir).expect("temp dir");
            Self(dir)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn open_store(dir: &TempDir) -> Arc<SegmentStore> {
        let (store, _) =
            SegmentStore::open(dir.0.join("recordings"), Vault::new(dir.0.join("vault")))
                .expect("store opens");
        Arc::new(store)
    }

    fn shared(dir: &TempDir) -> Arc<ProctoringShared> {
        let queue = EventQueue::open(&dir.0.join("proctoring"), "session-1").expect("queue");
        let policy: SessionPolicy = serde_json::from_value(json!({
            "proctor_session_id": "session-1", "policy_version": 1
        }))
        .expect("policy");
        Arc::new(ProctoringShared::new(
            Arc::new(queue),
            DeviceRules::from_policy(&policy),
        ))
    }

    fn face_event() -> FaceEvent {
        serde_json::from_value(json!({
            "event": "FACE_ABSENT", "source": "camera",
            "started_at": "2026-10-12T05:01:02.120Z", "duration_ms": 5000,
            "confidence": 0.9, "details": { "phase": "started" }
        }))
        .expect("event")
    }

    fn camera_headers(seq: &str) -> impl Fn(&str) -> Option<String> + use<> {
        let seq = seq.to_owned();
        move |name| {
            Some(match name {
                "x-hv-track" => "camera".to_owned(),
                "x-hv-seq" => seq.clone(),
                "x-hv-started-at-ms" => "1760245400123".to_owned(),
                "x-hv-duration-ms" => "10000".to_owned(),
                "x-hv-container" => "mp4".to_owned(),
                "x-hv-codec" => "h264".to_owned(),
                _ => return None,
            })
        }
    }

    #[test]
    fn a_face_event_is_queued_with_the_next_seq() {
        let dir = TempDir::new();
        let shared = shared(&dir);
        assert_eq!(shared.enqueue(face_event()).expect("queued"), 1);
        assert_eq!(shared.enqueue(face_event()).expect("queued"), 2);
        let queued = shared.queue.pending(0, 10);
        assert_eq!(queued.len(), 2);
        assert_eq!(queued[0].event, EventName::FaceAbsent);
        assert_eq!(queued[0].started_at, "2026-10-12T05:01:02.120Z");
    }

    #[test]
    fn reported_devices_feed_the_heartbeat() {
        let dir = TempDir::new();
        let shared = shared(&dir);
        assert_eq!(shared.device_status().camera, "off");
        shared
            .set_devices(Some("Integrated Camera".into()), Some(String::new()))
            .expect("devices");
        let status = shared.device_status();
        assert_eq!((status.camera.as_str(), status.mic.as_str()), ("on", "on"));
        shared.set_devices(None, None).expect("devices");
        assert_eq!(shared.device_status().camera, "off");
        assert_eq!(
            shared
                .set_devices(Some("bad\nlabel".into()), None)
                .unwrap_err()
                .code,
            "invalid-device"
        );
    }

    #[test]
    fn a_stopped_screen_shows_in_the_heartbeat() {
        let dir = TempDir::new();
        let shared = shared(&dir);
        shared.set_screen_capturing(true, Some(2));
        let status = shared.device_status();
        assert_eq!((status.screen.as_str(), status.displays), ("capturing", 2));
        shared.set_screen_capturing(false, None);
        assert_eq!(shared.device_status().screen, "stopped");
    }

    #[test]
    fn a_closed_sessions_queue_is_deleted() {
        let dir = TempDir::new();
        let shared = shared(&dir);
        shared.enqueue(face_event()).expect("queued");
        let queue_dir = shared.queue.dir().to_owned();
        assert!(queue_dir.exists());
        purge(shared);
        assert!(!queue_dir.exists());
    }

    #[test]
    fn a_queue_still_in_use_is_left_alone() {
        let dir = TempDir::new();
        let shared = shared(&dir);
        let queue_dir = shared.queue.dir().to_owned();
        let other = shared.clone();
        purge(shared);
        assert!(queue_dir.exists());
        drop(other);
    }

    #[test]
    fn a_display_failure_is_a_screen_capture_stopped_event() {
        let draft = screen_stopped("screen-2", "capture_failed", 1_760_245_400_123);
        assert_eq!(draft.event, EventName::ScreenCaptureStopped);
        assert_eq!(draft.source, Source::Screen);
        assert_eq!(draft.started_at_ms, 1_760_245_400_123);
        assert_eq!(draft.details["track"], "screen-2");
    }

    #[test]
    fn screen_segments_become_mp4_h264_rows() {
        let new = screen_segment(INTERVIEW, "screen-2", 7, 1_760_245_400_123, 10_000).expect("ok");
        assert_eq!(new.track, Track::Screen(2));
        assert_eq!((new.container, new.codec), (Container::Mp4, Codec::H264));
        assert_eq!((new.seq, new.duration_ms), (7, 10_000));
        assert!(screen_segment(INTERVIEW, "camera", 0, 0, 1).is_err());
        assert!(screen_segment(INTERVIEW, "screen-0", 0, 0, 1).is_err());
        // A zero-length segment is stored as one millisecond, which the contract allows.
        assert_eq!(
            screen_segment(INTERVIEW, "screen-1", 0, 0, 0)
                .expect("ok")
                .duration_ms,
            1
        );
    }

    #[test]
    fn upload_events_are_mapped_to_what_the_app_does() {
        assert_eq!(
            react_to(&UploadEvent::TrackRefused {
                track: Track::Camera
            }),
            Reaction::StopTrack("camera".into())
        );
        // The screen is the native recorder's; there is no webview track to stop.
        assert_eq!(
            react_to(&UploadEvent::TrackRefused {
                track: Track::Screen(1)
            }),
            Reaction::Nothing
        );
        assert_eq!(
            react_to(&UploadEvent::Retrying {
                track: Track::Mic,
                seq: 3,
                code: "token-invalid".into(),
                delay: Duration::from_secs(1),
            }),
            Reaction::ForgetToken
        );
        assert_eq!(
            react_to(&UploadEvent::Acknowledged {
                track: Track::Mic,
                seq: 3
            }),
            Reaction::Nothing
        );
    }

    #[tokio::test]
    async fn a_camera_segment_is_stored_for_the_interview_rust_knows() {
        let dir = TempDir::new();
        let store = open_store(&dir);
        let woken = Arc::new(AtomicUsize::new(0));
        let intake = RecordingIntake {
            interview_id: INTERVIEW.to_owned(),
            store: store.clone(),
            wake: {
                let woken = woken.clone();
                Arc::new(move || {
                    woken.fetch_add(1, Ordering::Relaxed);
                })
            },
        };

        let stored = intake
            .store(camera_headers("4"), b"webm-or-mp4 bytes")
            .await
            .expect("stored");

        assert_eq!(stored.track, "camera");
        assert_eq!((stored.seq, stored.bytes), (4, 17));
        assert_eq!(stored.state, SegmentState::Captured.to_string());
        assert_eq!(woken.load(Ordering::Relaxed), 1);
        assert_eq!(store.pending(INTERVIEW).expect("pending").len(), 1);
    }

    #[tokio::test]
    async fn bad_segments_are_refused_with_codes_the_webview_knows() {
        let dir = TempDir::new();
        let intake = RecordingIntake {
            interview_id: INTERVIEW.to_owned(),
            store: open_store(&dir),
            wake: Arc::new(|| {}),
        };
        let wrong_track = |name: &str| {
            Some(match name {
                "x-hv-track" => "screen-1".to_owned(),
                other => camera_headers("0")(other)?,
            })
        };
        assert_eq!(
            intake.store(wrong_track, b"x").await.unwrap_err().code,
            "invalid-segment"
        );
        assert_eq!(
            intake
                .store(camera_headers("0"), b"")
                .await
                .unwrap_err()
                .code,
            "invalid-segment"
        );
        intake
            .store(camera_headers("0"), b"first")
            .await
            .expect("stored");
        assert_eq!(
            intake
                .store(camera_headers("0"), b"different")
                .await
                .unwrap_err()
                .code,
            "segment-conflict"
        );
    }

    #[tokio::test]
    async fn stopping_for_exit_is_safe_inside_a_runtime() {
        // The updater's before-exit hook runs on an async worker; block_on there must not panic.
        Services::disabled().stop_for_exit();
    }

    #[tokio::test]
    async fn the_stub_services_do_nothing_and_succeed() {
        let services = Services::disabled();
        let notify: Notify = Arc::new(|_, _| {});
        let started = services
            .start(notify, INTERVIEW, Vec::new())
            .await
            .expect("start");
        assert_eq!(started, ServicesStarted::default());
        services.stop(StopMode::Complete).await;
        assert!(services.set_devices(Some("cam".into()), None).is_ok());
        assert!(services.upload_progress(INTERVIEW).expect("progress").done);
        assert_eq!(
            services
                .store_segment(camera_headers("0"), b"x")
                .await
                .unwrap_err()
                .code,
            "recording-inactive"
        );
        assert_eq!(
            services.enqueue_face_event(face_event()).unwrap_err().code,
            "proctoring-inactive"
        );
        assert_eq!(services.clock_offset_ms().await, 0);
    }

    #[tokio::test]
    async fn a_bad_interview_id_never_starts_anything() {
        let services = Services::disabled();
        let notify: Notify = Arc::new(|_, _| {});
        let error = services
            .start(notify, "../etc", Vec::new())
            .await
            .unwrap_err();
        assert_eq!(error.code, "invalid-interview");
        assert_eq!(
            services.upload_progress("a/b").unwrap_err().code,
            "invalid-interview"
        );
    }

    #[test]
    fn progress_reads_the_store_and_the_recording_flag() {
        let dir = TempDir::new();
        let store = open_store(&dir);
        store
            .put(
                NewSegment {
                    interview_id: INTERVIEW.to_owned(),
                    track: Track::Camera,
                    seq: 0,
                    started_at_ms: 1,
                    duration_ms: 1000,
                    container: Container::Mp4,
                    codec: Codec::H264,
                },
                b"segment",
            )
            .expect("put");
        let counts = store.counts(INTERVIEW).expect("counts");
        let progress = UploadProgress::from_counts(&counts, false);
        assert_eq!((progress.pending, progress.done), (1, false));
    }
}
