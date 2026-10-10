//! The uploader against a mock API (`docs/api/contracts/proctoring.md`).

use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use hv_api_client::{ApiClient, Url};
use hv_event_queue::{
    DeviceStatus, EventDraft, EventName, EventQueue, Source, UploadState, Uploader, UploaderConfig,
    open_session,
};
use hv_security::SoftwareKey;
use serde_json::{Value, json};
use wiremock::matchers::{header_exists, method, path};
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

const SESSION: &str = "0b0e6f9c-0000-4000-8000-00000000c0de";
const TOKEN: &str = "interview-session-token";

static NEXT: AtomicU32 = AtomicU32::new(0);

struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        let n = NEXT.fetch_add(1, Ordering::SeqCst);
        Self(std::env::temp_dir().join(format!("hv-uploader-test-{}-{n}", std::process::id())))
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn client(server: &MockServer) -> Arc<ApiClient> {
    let base = Url::parse(&format!("{}/api/v1", server.uri())).expect("base");
    Arc::new(
        ApiClient::new(
            base,
            Arc::new(SoftwareKey::generate()),
            "HirevionInterview/1.4.0 (Windows 26200; x64)".into(),
        )
        .expect("client"),
    )
}

fn fast(batch_max_events: usize) -> UploaderConfig {
    UploaderConfig {
        batch_max_events,
        heartbeat_interval: Duration::from_secs(3600),
        backoff_base: Duration::from_millis(10),
        backoff_max: Duration::from_millis(50),
        retry_after_max: Duration::from_millis(50),
    }
}

fn status() -> Arc<dyn Fn() -> DeviceStatus + Send + Sync> {
    Arc::new(|| DeviceStatus {
        camera: "on".into(),
        mic: "on".into(),
        screen: "capturing".into(),
        third_eye: "connected".into(),
        displays: 1,
        cpu_percent: Some(31.0),
        vision_fps: Some(9.5),
    })
}

fn draft(at: i64) -> EventDraft {
    EventDraft::new(EventName::BlockedProcessDetected, Source::Native, at)
}

/// The `POST /proctoring/events` requests received (heartbeats also start at once).
async fn event_requests(server: &MockServer) -> Vec<Request> {
    server
        .received_requests()
        .await
        .expect("requests")
        .into_iter()
        .filter(|r| r.url.path().ends_with("/proctoring/events"))
        .collect()
}

fn seqs_of(request: &Request) -> Vec<u64> {
    let body: Value = serde_json::from_slice(&request.body).expect("json body");
    body["events"]
        .as_array()
        .expect("events")
        .iter()
        .map(|e| e["seq"].as_u64().expect("seq"))
        .collect()
}

/// A server that stores events, answers with the contiguous high mark and the gaps, and can
/// drop chosen sequence numbers the first time they arrive.
#[derive(Clone, Default)]
struct Store {
    stored: Arc<Mutex<BTreeSet<u64>>>,
    drop_once: Arc<Mutex<BTreeSet<u64>>>,
}

impl Respond for Store {
    fn respond(&self, request: &Request) -> ResponseTemplate {
        let mut stored = self.stored.lock().expect("lock");
        let mut drop_once = self.drop_once.lock().expect("lock");
        for seq in seqs_of(request) {
            if !drop_once.remove(&seq) {
                stored.insert(seq);
            }
        }
        let high = stored.iter().copied().max().unwrap_or(0);
        let acked = (1..=high)
            .take_while(|s| stored.contains(s))
            .last()
            .unwrap_or(0);
        let missing: Vec<u64> = (acked + 1..high).filter(|s| !stored.contains(s)).collect();
        ResponseTemplate::new(200)
            .set_body_json(json!({ "acked_through": acked, "missing": missing }))
    }
}

#[tokio::test]
async fn opening_a_session_sends_the_interview_and_reads_the_policy() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/session"))
        .and(header_exists("DPoP"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "proctor_session_id": SESSION,
            "policy_version": 3,
            "level": "standard",
            "checks": ["focus", "processes", "displays"],
            "thresholds": {},
            "app_rules": { "blocked": [], "allowed": [] },
            "single_display": true,
            "heartbeat_seconds": 5,
            "batch_max_events": 100,
            "accommodations": []
        })))
        .expect(1)
        .mount(&server)
        .await;
    let api = client(&server);
    let policy = open_session(&api, TOKEN, "interview-1", "1.4.0")
        .await
        .expect("session");
    assert_eq!(policy.proctor_session_id, SESSION);
    assert!(policy.single_display);
    let request = &server.received_requests().await.expect("requests")[0];
    assert_eq!(
        request
            .headers
            .get("Authorization")
            .expect("auth")
            .to_str()
            .expect("ascii"),
        format!("DPoP {TOKEN}")
    );
    let body: Value = serde_json::from_slice(&request.body).expect("json");
    assert_eq!(
        body,
        json!({ "interview_id": "interview-1", "app_version": "1.4.0" })
    );
}

#[tokio::test]
async fn events_go_up_in_batches_of_at_most_batch_max_events() {
    let server = MockServer::start().await;
    let store = Store::default();
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/events"))
        .respond_with(store.clone())
        .mount(&server)
        .await;
    let dir = TempDir::new();
    let queue = Arc::new(EventQueue::open(&dir.0, SESSION).expect("queue"));
    for i in 0..5 {
        queue.append(draft(i)).expect("append");
    }
    let uploader = Uploader::spawn(
        client(&server),
        queue.clone(),
        SESSION.into(),
        TOKEN.into(),
        status(),
        fast(2),
    );
    assert!(
        uploader.flush(Duration::from_secs(5)).await,
        "everything acknowledged"
    );
    uploader.stop().await;

    let requests = event_requests(&server).await;
    let batches: Vec<Vec<u64>> = requests.iter().map(seqs_of).collect();
    assert_eq!(batches, [vec![1, 2], vec![3, 4], vec![5]]);
    let body: Value = serde_json::from_slice(&requests[0].body).expect("json");
    assert_eq!(body["proctor_session_id"], SESSION);
    assert_eq!(body["events"][0]["event"], "BLOCKED_PROCESS_DETECTED");
    assert!(requests[0].headers.get("DPoP").is_some());
    assert_eq!(queue.acked_through(), 5);
    assert!(queue.is_drained());
}

#[tokio::test]
async fn what_the_server_lists_as_missing_is_sent_again() {
    let server = MockServer::start().await;
    let store = Store::default();
    store.drop_once.lock().expect("lock").insert(2);
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/events"))
        .respond_with(store.clone())
        .mount(&server)
        .await;
    let dir = TempDir::new();
    let queue = Arc::new(EventQueue::open(&dir.0, SESSION).expect("queue"));
    for i in 0..3 {
        queue.append(draft(i)).expect("append");
    }
    let uploader = Uploader::spawn(
        client(&server),
        queue.clone(),
        SESSION.into(),
        TOKEN.into(),
        status(),
        fast(10),
    );
    assert!(uploader.flush(Duration::from_secs(5)).await);
    uploader.stop().await;

    let batches: Vec<Vec<u64>> = event_requests(&server).await.iter().map(seqs_of).collect();
    assert_eq!(
        batches,
        [vec![1, 2, 3], vec![2]],
        "only the missing event is resent"
    );
    assert_eq!(queue.acked_through(), 3);
}

#[tokio::test]
async fn a_failing_server_is_retried_with_backoff() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/events"))
        .respond_with(ResponseTemplate::new(503).set_body_json(json!({
            "type": "about:blank", "title": "Unavailable", "status": 503, "code": "unavailable"
        })))
        .up_to_n_times(2)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/events"))
        .respond_with(Store::default())
        .mount(&server)
        .await;
    let dir = TempDir::new();
    let queue = Arc::new(EventQueue::open(&dir.0, SESSION).expect("queue"));
    queue.append(draft(1)).expect("append");
    let uploader = Uploader::spawn(
        client(&server),
        queue.clone(),
        SESSION.into(),
        TOKEN.into(),
        status(),
        fast(10),
    );
    assert!(uploader.flush(Duration::from_secs(5)).await);
    assert_eq!(uploader.state(), UploadState::Idle);
    uploader.stop().await;
    assert_eq!(event_requests(&server).await.len(), 3);
}

#[tokio::test]
async fn a_closed_proctor_session_stops_the_uploader() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/events"))
        .respond_with(ResponseTemplate::new(409).set_body_json(json!({
            "type": "about:blank", "title": "Closed", "status": 409, "code": "proctor-session-closed"
        })))
        .mount(&server)
        .await;
    let dir = TempDir::new();
    let queue = Arc::new(EventQueue::open(&dir.0, SESSION).expect("queue"));
    queue.append(draft(1)).expect("append");
    let uploader = Uploader::spawn(
        client(&server),
        queue.clone(),
        SESSION.into(),
        TOKEN.into(),
        status(),
        fast(10),
    );
    let mut state = uploader.subscribe();
    tokio::time::timeout(
        Duration::from_secs(5),
        state.wait_for(|s| *s == UploadState::Closed),
    )
    .await
    .expect("closed in time")
    .expect("state channel");
    queue.append(draft(2)).expect("append after close");
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert_eq!(
        event_requests(&server).await.len(),
        1,
        "nothing is sent after the session closed"
    );
    assert!(uploader.is_finished());
    uploader.stop().await;
}

#[tokio::test]
async fn heartbeats_carry_the_high_sequence_and_the_device_status() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/heartbeat"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({ "server_time": "2026-10-12T05:01:02.120Z", "missing": [] })),
        )
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/events"))
        .respond_with(Store::default())
        .mount(&server)
        .await;
    let dir = TempDir::new();
    let queue = Arc::new(EventQueue::open(&dir.0, SESSION).expect("queue"));
    queue.append(draft(1)).expect("append");
    queue.append(draft(2)).expect("append");
    let config = UploaderConfig {
        heartbeat_interval: Duration::from_millis(50),
        ..fast(10)
    };
    let uploader = Uploader::spawn(
        client(&server),
        queue,
        SESSION.into(),
        TOKEN.into(),
        status(),
        config,
    );
    tokio::time::sleep(Duration::from_millis(200)).await;
    uploader.stop().await;

    let heartbeats: Vec<Value> = server
        .received_requests()
        .await
        .expect("requests")
        .iter()
        .filter(|r| r.url.path().ends_with("/heartbeat"))
        .map(|r| serde_json::from_slice(&r.body).expect("json"))
        .collect();
    assert!(heartbeats.len() >= 2, "{heartbeats:?}");
    assert_eq!(
        heartbeats[0],
        json!({
            "proctor_session_id": SESSION, "seq_high": 2, "camera": "on", "mic": "on",
            "screen": "capturing", "third_eye": "connected", "displays": 1,
            "cpu_percent": 31.0, "vision_fps": 9.5
        })
    );
}
