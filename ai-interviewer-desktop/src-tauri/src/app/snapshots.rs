//! Evidence pictures the server asks for (contract proctoring.md, "Changes": the heartbeat
//! answer's `snapshot_requests`). When a CRITICAL event is raised the server asks for a screen
//! picture, and a camera one where the camera matters; each request is answered once, within
//! its two minutes, with `POST /proctoring/evidence-uploads` naming the `request_id`.
//!
//! - The screen picture is taken here (Windows Graphics Capture, one frame, JPEG by WIC).
//! - The camera picture comes from the webview, which owns the interview's camera track: Rust
//!   asks for it (`hv:snapshot-request`) and takes back only a JPEG for a request it made.
//! - Nothing blocks the interview: each request runs on its own, and a failure is logged.

use std::collections::HashMap;
use std::future::Future;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use hv_api_client::SessionManager;
use hv_event_queue::{SnapshotKind, SnapshotRequest};
use hv_uploader::{BlobClient, EvidenceAnswer, MAX_EVIDENCE_BYTES, upload_evidence};
use serde_json::json;
use tokio::sync::{mpsc, oneshot};

use super::interview::{SessionTokens, session_token};
use super::services::Notify;

/// The event that asks the webview for one camera frame (payload: `{ request_id }`).
pub const SNAPSHOT_EVENT: &str = "hv:snapshot-request";
/// How long the webview has to hand back a camera frame.
pub const CAMERA_WAIT: Duration = Duration::from_secs(10);
const FIRST_RETRY: Duration = Duration::from_secs(1);
const LONGEST_RETRY: Duration = Duration::from_secs(15);
/// The last try is made this long before the request expires, so it can still arrive in time.
const LAST_TRY_MS: i64 = 1_000;
const JPEG_START: [u8; 3] = [0xFF, 0xD8, 0xFF];

/// How sending an answer failed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Failure {
    /// The server won't take it (an unknown request, a picture already sent): stop.
    Final(String),
    /// Offline, busy or a stale token: try again while the request is open.
    Retry(String),
}

/// What became of one request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    Answered,
    /// Its two minutes ran out (or its time couldn't be read).
    Expired,
    Refused(String),
    /// No picture could be taken.
    NoPicture(String),
}

/// Takes the picture a request asks for, as JPEG bytes.
pub trait Pictures: Send + Sync {
    fn take(
        &self,
        request: &SnapshotRequest,
    ) -> impl Future<Output = Result<Vec<u8>, String>> + Send;
}

/// Sends one picture as the answer to its request.
pub trait Answers: Send + Sync {
    fn send(
        &self,
        request: &SnapshotRequest,
        picture: Vec<u8>,
    ) -> impl Future<Output = Result<(), Failure>> + Send;
}

/// The server's clock (milliseconds) and a way to wait.
pub trait Time: Send + Sync {
    fn now_ms(&self) -> i64;
    fn sleep(&self, wait: Duration) -> impl Future<Output = ()> + Send;
}

/// Answers one request: takes its picture once, then sends it, retrying with growing waits
/// while the request is open.
pub async fn answer(
    request: &SnapshotRequest,
    pictures: &impl Pictures,
    answers: &impl Answers,
    time: &impl Time,
) -> Outcome {
    let Some(expires_at) = request.expires_at_ms() else {
        return Outcome::Expired;
    };
    if time.now_ms() >= expires_at {
        return Outcome::Expired;
    }
    let picture = match pictures.take(request).await {
        Ok(picture) => picture,
        Err(why) => return Outcome::NoPicture(why),
    };
    let mut wait = FIRST_RETRY;
    loop {
        match answers.send(request, picture.clone()).await {
            Ok(()) => return Outcome::Answered,
            Err(Failure::Final(code)) => return Outcome::Refused(code),
            Err(Failure::Retry(_)) => {
                // Wait as planned, but never past the last moment worth a try.
                let room = expires_at - LAST_TRY_MS - time.now_ms();
                if room <= 0 {
                    return Outcome::Expired;
                }
                let room = Duration::from_millis(u64::try_from(room).unwrap_or(0));
                time.sleep(wait.min(room)).await;
                wait = (wait * 2).min(LONGEST_RETRY);
            }
        }
    }
}

/// Lets a request be handed on again when a later heartbeat repeats it.
pub type Release = Arc<dyn Fn(&str) + Send + Sync>;

/// Answers every request from the heartbeat until the channel closes, each on its own task so
/// a slow one never holds up the next. The tasks belong to this future: when it is stopped
/// (the proctor session ended), the answers in flight stop with it. A request that got no
/// picture here is released, so the server's repeat of it is answered.
pub async fn answer_all<P, A, T>(
    mut requests: mpsc::Receiver<SnapshotRequest>,
    pictures: Arc<P>,
    answers: Arc<A>,
    time: Arc<T>,
    release: Release,
) where
    P: Pictures + 'static,
    A: Answers + 'static,
    T: Time + 'static,
{
    let mut running = tokio::task::JoinSet::new();
    loop {
        tokio::select! {
            request = requests.recv() => {
                let Some(request) = request else { break };
                let (pictures, answers, time, release) =
                    (pictures.clone(), answers.clone(), time.clone(), release.clone());
                running.spawn(async move {
                    let outcome = answer(&request, &*pictures, &*answers, &*time).await;
                    if matches!(outcome, Outcome::NoPicture(_)) {
                        release(&request.request_id);
                    }
                    if outcome != Outcome::Answered {
                        eprintln!(
                            "proctoring: snapshot {} ({}) not answered: {outcome:?}",
                            request.request_id,
                            request.kind.as_str()
                        );
                    }
                });
            }
            Some(_) = running.join_next(), if !running.is_empty() => {}
        }
    }
    while running.join_next().await.is_some() {}
}

pub fn is_jpeg(bytes: &[u8]) -> bool {
    bytes.starts_with(&JPEG_START)
}

/// Camera frames the webview owes: a frame is taken only for a request Rust made, once.
#[derive(Default)]
pub struct CameraFrames {
    waiting: Mutex<HashMap<String, oneshot::Sender<Vec<u8>>>>,
}

impl CameraFrames {
    /// Notes that a frame is wanted for `request_id`; the receiver gets it.
    pub fn expect(&self, request_id: &str) -> oneshot::Receiver<Vec<u8>> {
        let (sender, receiver) = oneshot::channel();
        if let Ok(mut waiting) = self.waiting.lock() {
            waiting.insert(request_id.to_owned(), sender);
        }
        receiver
    }

    /// The webview's frame for `request_id`: refused unless it was asked for and is a JPEG
    /// within the server's limit. Checked before anything is copied.
    pub fn deliver(&self, request_id: &str, jpeg: &[u8]) -> Result<(), &'static str> {
        if !is_jpeg(jpeg) {
            return Err("not-a-jpeg");
        }
        if jpeg.len() > MAX_EVIDENCE_BYTES {
            return Err("too-large");
        }
        let sender = self
            .waiting
            .lock()
            .ok()
            .and_then(|mut waiting| waiting.remove(request_id));
        match sender {
            Some(sender) => sender.send(jpeg.to_vec()).map_err(|_| "not-requested"),
            None => Err("not-requested"),
        }
    }

    pub fn forget(&self, request_id: &str) {
        if let Ok(mut waiting) = self.waiting.lock() {
            waiting.remove(request_id);
        }
    }
}

/// Waits for the webview's frame for `request`, after asking for it with `ask`.
pub async fn camera_frame(
    frames: &CameraFrames,
    request: &SnapshotRequest,
    ask: impl FnOnce(),
    wait: Duration,
) -> Result<Vec<u8>, String> {
    let receiver = frames.expect(&request.request_id);
    ask();
    match tokio::time::timeout(wait, receiver).await {
        Ok(Ok(frame)) => Ok(frame),
        Ok(Err(_)) => Err("camera-frame-dropped".to_owned()),
        Err(_) => {
            frames.forget(&request.request_id);
            Err("camera-frame-timeout".to_owned())
        }
    }
}

/// Whether `request` wants the screen.
pub fn wants_screen(request: &SnapshotRequest) -> bool {
    request.kind == SnapshotKind::Screen
}

/// The pictures the app takes during an interview.
pub struct LivePictures {
    pub notify: Notify,
    pub frames: Arc<CameraFrames>,
}

impl Pictures for LivePictures {
    async fn take(&self, request: &SnapshotRequest) -> Result<Vec<u8>, String> {
        if wants_screen(request) {
            return tauri::async_runtime::spawn_blocking(screen_jpeg)
                .await
                .map_err(|error| format!("screen-capture: {error}"))?;
        }
        let notify = self.notify.clone();
        let id = request.request_id.clone();
        camera_frame(
            &self.frames,
            request,
            move || notify(SNAPSHOT_EVENT, json!({ "request_id": id })),
            CAMERA_WAIT,
        )
        .await
    }
}

/// One frame of the primary display, at most 1280×720, as JPEG.
#[cfg(windows)]
fn screen_jpeg() -> Result<Vec<u8>, String> {
    use hv_screen_capture::geometry::Size;
    use hv_screen_capture::still::{capture_primary, encode_jpeg};
    let still = capture_primary(Duration::from_secs(3)).map_err(|error| error.to_string())?;
    encode_jpeg(
        &still,
        Size {
            width: 1280,
            height: 720,
        },
    )
    .map_err(|error| error.to_string())
}

#[cfg(not(windows))]
fn screen_jpeg() -> Result<Vec<u8>, String> {
    Err("screen-capture-unsupported".to_owned())
}

/// Sends answers with the interview's session token (and its DPoP proof, by the API client).
pub struct LiveAnswers {
    pub session: Arc<SessionManager>,
    pub tokens: Arc<SessionTokens>,
    pub interview_id: String,
    pub proctor_session_id: String,
    pub blob: BlobClient,
}

impl Answers for LiveAnswers {
    async fn send(&self, request: &SnapshotRequest, picture: Vec<u8>) -> Result<(), Failure> {
        let token = session_token(&self.session, &self.tokens, &self.interview_id)
            .await
            .map_err(|error| Failure::Retry(error.code().to_owned()))?;
        let answer = EvidenceAnswer {
            proctor_session_id: &self.proctor_session_id,
            request_id: &request.request_id,
            kind: request.kind.as_str(),
            content_type: "image/jpeg",
        };
        match upload_evidence(self.session.api(), &self.blob, &token, &answer, picture).await {
            Ok(_) => Ok(()),
            Err(error) if error.is_final() => Err(Failure::Final(error.code())),
            Err(error) => {
                if error.code() == "token-invalid" {
                    self.tokens.forget(&self.interview_id);
                }
                Err(Failure::Retry(error.code()))
            }
        }
    }
}

/// The server's clock (synced by the API client with `GET /time`).
pub struct LiveTime {
    pub session: Arc<SessionManager>,
}

impl Time for LiveTime {
    fn now_ms(&self) -> i64 {
        self.session.api().server_now_ms()
    }

    async fn sleep(&self, wait: Duration) {
        tokio::time::sleep(wait).await;
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicI64, AtomicUsize, Ordering};

    use super::*;

    const ASKED_AT: &str = "2026-11-14T10:00:00Z";
    const ASKED_MS: i64 = 1_794_650_400_000;

    fn request(kind: SnapshotKind) -> SnapshotRequest {
        SnapshotRequest {
            request_id: "0190f1a2-0000-7000-8000-000000000001".into(),
            event_id: "e1".into(),
            kind,
            requested_at: ASKED_AT.into(),
        }
    }

    struct Picture(Result<Vec<u8>, String>);
    impl Pictures for Picture {
        async fn take(&self, _request: &SnapshotRequest) -> Result<Vec<u8>, String> {
            self.0.clone()
        }
    }

    /// Answers from a script, then the last entry forever; counts the sends.
    struct Script {
        replies: Mutex<Vec<Result<(), Failure>>>,
        sent: AtomicUsize,
    }
    impl Script {
        fn new(replies: Vec<Result<(), Failure>>) -> Self {
            Self {
                replies: Mutex::new(replies),
                sent: AtomicUsize::new(0),
            }
        }
    }
    impl Answers for Script {
        async fn send(&self, _request: &SnapshotRequest, picture: Vec<u8>) -> Result<(), Failure> {
            assert!(is_jpeg(&picture));
            self.sent.fetch_add(1, Ordering::SeqCst);
            let mut replies = self.replies.lock().expect("lock");
            if replies.len() > 1 {
                replies.remove(0)
            } else {
                replies[0].clone()
            }
        }
    }

    /// A clock that moves only when the answerer sleeps.
    struct FakeTime(AtomicI64);
    impl Time for FakeTime {
        fn now_ms(&self) -> i64 {
            self.0.load(Ordering::SeqCst)
        }
        async fn sleep(&self, wait: Duration) {
            self.0.fetch_add(
                i64::try_from(wait.as_millis()).expect("small"),
                Ordering::SeqCst,
            );
        }
    }

    fn jpeg() -> Vec<u8> {
        vec![0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3]
    }

    #[tokio::test]
    async fn answers_once_the_upload_goes_through_after_retries() {
        let answers = Script::new(vec![
            Err(Failure::Retry("network".into())),
            Err(Failure::Retry("service-unavailable".into())),
            Ok(()),
        ]);
        let time = FakeTime(AtomicI64::new(ASKED_MS + 1_000));
        let outcome = answer(
            &request(SnapshotKind::Screen),
            &Picture(Ok(jpeg())),
            &answers,
            &time,
        )
        .await;
        assert_eq!(outcome, Outcome::Answered);
        assert_eq!(answers.sent.load(Ordering::SeqCst), 3);
        // Waited 1 s, then 2 s.
        assert_eq!(time.now_ms(), ASKED_MS + 4_000);
    }

    #[tokio::test]
    async fn stops_at_a_final_refusal() {
        let answers = Script::new(vec![Err(Failure::Final(
            "snapshot-request-not-found".into(),
        ))]);
        let time = FakeTime(AtomicI64::new(ASKED_MS));
        let outcome = answer(
            &request(SnapshotKind::Camera),
            &Picture(Ok(jpeg())),
            &answers,
            &time,
        )
        .await;
        assert_eq!(
            outcome,
            Outcome::Refused("snapshot-request-not-found".into())
        );
        assert_eq!(answers.sent.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn gives_up_when_the_two_minutes_run_out() {
        let answers = Script::new(vec![Err(Failure::Retry("network".into()))]);
        let time = FakeTime(AtomicI64::new(ASKED_MS));
        let outcome = answer(
            &request(SnapshotKind::Screen),
            &Picture(Ok(jpeg())),
            &answers,
            &time,
        )
        .await;
        assert_eq!(outcome, Outcome::Expired);
        // Never waits past the request's expiry.
        assert!(time.now_ms() < ASKED_MS + 120_000);
        assert!(answers.sent.load(Ordering::SeqCst) > 5);
    }

    #[tokio::test]
    async fn an_expired_request_takes_no_picture_and_sends_nothing() {
        let answers = Script::new(vec![Ok(())]);
        let time = FakeTime(AtomicI64::new(ASKED_MS + 120_000));
        let outcome = answer(
            &request(SnapshotKind::Screen),
            &Picture(Ok(jpeg())),
            &answers,
            &time,
        )
        .await;
        assert_eq!(outcome, Outcome::Expired);
        assert_eq!(answers.sent.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn no_picture_means_nothing_is_sent() {
        let answers = Script::new(vec![Ok(())]);
        let time = FakeTime(AtomicI64::new(ASKED_MS));
        let pictures = Picture(Err("camera-frame-timeout".into()));
        let outcome = answer(&request(SnapshotKind::Camera), &pictures, &answers, &time).await;
        assert_eq!(outcome, Outcome::NoPicture("camera-frame-timeout".into()));
        assert_eq!(answers.sent.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn takes_a_camera_frame_only_for_a_request_it_made() {
        let frames = CameraFrames::default();
        let wanted = request(SnapshotKind::Camera);
        // Nothing asked: a frame is refused, as is anything that isn't a JPEG.
        assert_eq!(
            frames.deliver(&wanted.request_id, &jpeg()),
            Err("not-requested")
        );
        let frame = camera_frame(
            &frames,
            &wanted,
            || {
                assert_eq!(
                    frames.deliver(&wanted.request_id, b"GIF89a"),
                    Err("not-a-jpeg")
                );
                assert_eq!(frames.deliver(&wanted.request_id, &jpeg()), Ok(()));
            },
            CAMERA_WAIT,
        )
        .await;
        assert_eq!(frame, Ok(jpeg()));
        // Used once: the same request can't deliver again.
        assert_eq!(
            frames.deliver(&wanted.request_id, &jpeg()),
            Err("not-requested")
        );
    }

    #[tokio::test]
    async fn a_camera_frame_that_never_comes_times_out_and_is_forgotten() {
        let frames = CameraFrames::default();
        let wanted = request(SnapshotKind::Camera);
        let frame = camera_frame(&frames, &wanted, || {}, Duration::from_millis(20)).await;
        assert_eq!(frame, Err("camera-frame-timeout".into()));
        assert_eq!(
            frames.deliver(&wanted.request_id, &jpeg()),
            Err("not-requested")
        );
    }

    #[test]
    fn refuses_a_frame_over_the_servers_limit() {
        let frames = CameraFrames::default();
        let _receiver = frames.expect("r1");
        let mut big = jpeg();
        big.resize(MAX_EVIDENCE_BYTES + 1, 0);
        assert_eq!(frames.deliver("r1", &big), Err("too-large"));
    }

    #[tokio::test]
    async fn uses_the_last_seconds_before_the_request_expires() {
        // 10 s left: waits of 1, 2 and 4 s, then the last try waits only 2 s, not 8.
        let answers = Script::new(vec![
            Err(Failure::Retry("network".into())),
            Err(Failure::Retry("network".into())),
            Err(Failure::Retry("network".into())),
            Err(Failure::Retry("network".into())),
            Ok(()),
        ]);
        let time = FakeTime(AtomicI64::new(ASKED_MS + 110_000));
        let outcome = answer(
            &request(SnapshotKind::Screen),
            &Picture(Ok(jpeg())),
            &answers,
            &time,
        )
        .await;
        assert_eq!(outcome, Outcome::Answered);
        assert_eq!(answers.sent.load(Ordering::SeqCst), 5);
        assert!(time.now_ms() < ASKED_MS + 120_000);
    }

    #[tokio::test]
    async fn a_request_with_no_picture_can_come_again() {
        let (sender, receiver) = mpsc::channel(4);
        let released = Arc::new(Mutex::new(Vec::<String>::new()));
        let noted = released.clone();
        let task = tokio::spawn(answer_all(
            receiver,
            Arc::new(Picture(Err("camera-frame-timeout".into()))),
            Arc::new(Script::new(vec![Ok(())])),
            Arc::new(FakeTime(AtomicI64::new(ASKED_MS))),
            Arc::new(move |id: &str| noted.lock().expect("lock").push(id.to_owned())),
        ));
        sender
            .send(request(SnapshotKind::Camera))
            .await
            .expect("sent");
        drop(sender);
        task.await.expect("finished");
        // The server repeats its request in later heartbeats: it can be handed on again.
        assert_eq!(
            *released.lock().expect("lock"),
            vec![request(SnapshotKind::Camera).request_id]
        );
    }

    /// Notes when the picture it was taking is dropped (its task stopped).
    struct Endless(Arc<AtomicUsize>);
    struct Dropped(Arc<AtomicUsize>);
    impl Drop for Dropped {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    impl Pictures for Endless {
        async fn take(&self, _request: &SnapshotRequest) -> Result<Vec<u8>, String> {
            let _dropped = Dropped(self.0.clone());
            std::future::pending::<()>().await;
            Ok(jpeg())
        }
    }

    #[tokio::test]
    async fn stopping_the_answerer_stops_the_answers_in_flight() {
        let (sender, receiver) = mpsc::channel(4);
        let dropped = Arc::new(AtomicUsize::new(0));
        let task = tokio::spawn(answer_all(
            receiver,
            Arc::new(Endless(dropped.clone())),
            Arc::new(Script::new(vec![Ok(())])),
            Arc::new(FakeTime(AtomicI64::new(ASKED_MS))),
            Arc::new(|_: &str| {}),
        ));
        sender
            .send(request(SnapshotKind::Screen))
            .await
            .expect("sent");
        tokio::time::sleep(Duration::from_millis(20)).await;
        task.abort();
        let _ = task.await;
        tokio::time::sleep(Duration::from_millis(20)).await;
        // The session ended: the picture being taken for it is abandoned, not finished later.
        assert_eq!(dropped.load(Ordering::SeqCst), 1);
    }
}
