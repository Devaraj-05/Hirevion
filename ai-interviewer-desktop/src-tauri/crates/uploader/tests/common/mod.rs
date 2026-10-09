//! A fake recordings server (upload URLs, blob storage, hash-checked acks, the recovery
//! listing) on wiremock, and helpers for the uploader tests.
#![allow(dead_code)]

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use hv_api_client::{ApiClient, ApiError, Url};
use hv_security::SoftwareKey;
use hv_segment_store::{Codec, Container, NewSegment, SegmentStore, Track, sha256_hex};
use hv_uploader::{RecordingSession, TokenFuture, UploadEvent, Uploader, UploaderConfig};
use tokio::sync::broadcast;
use wiremock::matchers::{method, path, path_regex};
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

pub const INTERVIEW: &str = "0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6";
pub const TOKEN: &str = "interview-session-token";

pub struct TempDir(pub PathBuf);

impl TempDir {
    pub fn new() -> Self {
        let dir = std::env::temp_dir().join(format!("hv-uploader-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).expect("temp dir");
        Self(dir)
    }

    pub fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

pub fn open_store(root: &Path) -> Arc<SegmentStore> {
    let (store, _) = SegmentStore::open(
        root.join("segments"),
        hv_security::Vault::new(root.join("vault")),
    )
    .expect("store opens");
    Arc::new(store)
}

pub fn segment(track: Track, seq: u64) -> NewSegment {
    let (container, codec) = match track {
        Track::Mic => (Container::Webm, Codec::Opus),
        _ => (Container::Mp4, Codec::H264),
    };
    NewSegment {
        interview_id: INTERVIEW.to_owned(),
        track,
        seq,
        started_at_ms: 1_700_000_000_123 + i64::try_from(seq).expect("small") * 10_000,
        duration_ms: 10_000,
        container,
        codec,
    }
}

pub fn payload(seq: u64, len: usize) -> Vec<u8> {
    (0..len)
        .map(|i| u8::try_from((i as u64 * 31 + seq * 7) % 251).expect("byte"))
        .collect()
}

/// The interview-session side the uploader needs: the DPoP client and a token.
pub struct TestSession {
    pub api: ApiClient,
}

impl RecordingSession for TestSession {
    fn api(&self) -> &ApiClient {
        &self.api
    }

    fn token(&self) -> TokenFuture<'_> {
        Box::pin(async { Ok::<_, ApiError>(TOKEN.to_owned()) })
    }
}

pub fn session_for(base: &str) -> Arc<TestSession> {
    let base = Url::parse(&format!("{base}/api/v1")).expect("base url");
    let api = ApiClient::new(base, Arc::new(SoftwareKey::generate()), "test".into()).expect("api");
    Arc::new(TestSession { api })
}

/// Fast backoff, so retries happen within a test.
pub fn fast_config() -> UploaderConfig {
    UploaderConfig {
        backoff_base: Duration::from_millis(5),
        backoff_cap: Duration::from_millis(40),
        ..UploaderConfig::default()
    }
}

pub fn uploader(base: &str, store: &Arc<SegmentStore>) -> Arc<Uploader> {
    Arc::new(Uploader::new(session_for(base), Arc::clone(store), fast_config()).expect("uploader"))
}

/// Every event received so far.
pub fn drain_events(events: &mut broadcast::Receiver<UploadEvent>) -> Vec<UploadEvent> {
    let mut seen = Vec::new();
    while let Ok(event) = events.try_recv() {
        seen.push(event);
    }
    seen
}

#[derive(Default)]
pub struct ServerState {
    /// segment_id → (declared sha256, declared bytes).
    pub declared: HashMap<String, (String, u64)>,
    /// Blob path → uploaded bytes.
    pub blobs: HashMap<String, Vec<u8>>,
    pub acknowledged: BTreeSet<(String, u64)>,
    /// Tracks the interview doesn't record.
    pub not_recorded: BTreeSet<String>,
    /// Corrupt the next N uploads (flip a byte), to force a hash mismatch.
    pub corrupt_next: usize,
    /// Drop the next N uploads (answer 201, store nothing), to force blob-missing.
    pub lose_next: usize,
    /// Answer the next N URL requests with 503.
    pub fail_urls: usize,
    /// Answer the next N PUTs with 500.
    pub fail_puts: usize,
    /// Answer the next N acks with 503.
    pub fail_acks: usize,
    /// Refuse uploads larger than this with 413.
    pub max_bytes: Option<u64>,
    /// The upload URL's origin, when it should differ from the server's.
    pub upload_origin: Option<String>,
}

/// The fake server and its state.
pub struct Fake {
    pub server: MockServer,
    pub state: Arc<Mutex<ServerState>>,
}

impl Fake {
    pub async fn start() -> Self {
        Self::on(MockServer::start().await).await
    }

    pub async fn on(server: MockServer) -> Self {
        let state = Arc::new(Mutex::new(ServerState::default()));
        let uri = server.uri();
        Mock::given(method("POST"))
            .and(path("/api/v1/recordings/segments"))
            .respond_with(UrlRespond {
                state: Arc::clone(&state),
                origin: uri.clone(),
            })
            .mount(&server)
            .await;
        Mock::given(method("PUT"))
            .and(path_regex("^/blob/"))
            .respond_with(BlobRespond(Arc::clone(&state)))
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path_regex("^/api/v1/recordings/segments/[^/]+/ack$"))
            .respond_with(AckRespond(Arc::clone(&state)))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path_regex("^/api/v1/recordings/interviews/[^/]+/segments$"))
            .respond_with(ListingRespond(Arc::clone(&state)))
            .mount(&server)
            .await;
        Self { server, state }
    }

    pub fn uri(&self) -> String {
        self.server.uri()
    }

    pub fn with<T>(&self, change: impl FnOnce(&mut ServerState) -> T) -> T {
        change(&mut self.state.lock().expect("state"))
    }

    pub async fn requests(&self, verb: &str, prefix: &str) -> Vec<Request> {
        self.server
            .received_requests()
            .await
            .unwrap_or_default()
            .into_iter()
            .filter(|r| r.method.as_str() == verb && r.url.path().starts_with(prefix))
            .collect()
    }
}

pub fn problem(status: u16, code: &str) -> ResponseTemplate {
    ResponseTemplate::new(status).set_body_json(serde_json::json!({
        "type": format!("https://hirevion.example.test/problems/{code}"),
        "title": "Problem",
        "status": status,
        "code": code,
    }))
}

struct UrlRespond {
    state: Arc<Mutex<ServerState>>,
    origin: String,
}

impl Respond for UrlRespond {
    fn respond(&self, request: &Request) -> ResponseTemplate {
        let body: serde_json::Value = serde_json::from_slice(&request.body).expect("json body");
        let track = body["track"].as_str().expect("track").to_owned();
        let seq = body["seq"].as_u64().expect("seq");
        let mut state = self.state.lock().expect("state");
        if state.fail_urls > 0 {
            state.fail_urls -= 1;
            return problem(503, "unavailable");
        }
        if state.not_recorded.contains(&track) {
            return problem(422, "track-not-recorded");
        }
        let bytes = body["bytes"].as_u64().expect("bytes");
        if state.max_bytes.is_some_and(|max| bytes > max) {
            return problem(413, "segment-too-large");
        }
        if state.acknowledged.contains(&(track.clone(), seq)) {
            return problem(409, "segment-acknowledged");
        }
        let segment_id = format!("{track}-{seq}");
        state.declared.insert(
            segment_id.clone(),
            (body["sha256"].as_str().expect("sha").to_owned(), bytes),
        );
        let origin = state
            .upload_origin
            .clone()
            .unwrap_or_else(|| self.origin.clone());
        let content_type = if track == "mic" {
            "audio/webm"
        } else {
            "video/mp4"
        };
        ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "segment_id": segment_id,
            "upload_url": format!("{origin}/blob/{segment_id}?sv=2025&sig=write-only"),
            "headers": { "x-ms-blob-type": "BlockBlob", "Content-Type": content_type },
            "expires_at": "2999-01-01T00:00:00.000Z",
        }))
    }
}

struct BlobRespond(Arc<Mutex<ServerState>>);

impl Respond for BlobRespond {
    fn respond(&self, request: &Request) -> ResponseTemplate {
        let mut state = self.0.lock().expect("state");
        if state.fail_puts > 0 {
            state.fail_puts -= 1;
            return ResponseTemplate::new(500);
        }
        if request.headers.get("x-ms-blob-type").is_none() {
            return ResponseTemplate::new(400);
        }
        if state.lose_next > 0 {
            state.lose_next -= 1;
            return ResponseTemplate::new(201);
        }
        let mut body = request.body.clone();
        if state.corrupt_next > 0 && !body.is_empty() {
            state.corrupt_next -= 1;
            body[0] ^= 0xFF;
        }
        let id = request.url.path().trim_start_matches("/blob/").to_owned();
        state.blobs.insert(id, body);
        ResponseTemplate::new(201)
    }
}

struct AckRespond(Arc<Mutex<ServerState>>);

impl Respond for AckRespond {
    fn respond(&self, request: &Request) -> ResponseTemplate {
        let mut state = self.0.lock().expect("state");
        if state.fail_acks > 0 {
            state.fail_acks -= 1;
            return problem(503, "unavailable");
        }
        let segment_id = request
            .url
            .path()
            .trim_start_matches("/api/v1/recordings/segments/")
            .trim_end_matches("/ack")
            .to_owned();
        let body: serde_json::Value = serde_json::from_slice(&request.body).expect("json");
        let Some((declared_sha, declared_bytes)) = state.declared.get(&segment_id).cloned() else {
            return problem(404, "not-found");
        };
        let Some(blob) = state.blobs.get(&segment_id).cloned() else {
            return problem(404, "blob-missing");
        };
        if body["sha256"].as_str() != Some(declared_sha.as_str())
            || sha256_hex(&blob) != declared_sha
            || blob.len() as u64 != declared_bytes
        {
            state.blobs.remove(&segment_id);
            return problem(422, "hash-mismatch");
        }
        let (track, seq) = segment_id.rsplit_once('-').expect("track-seq");
        state
            .acknowledged
            .insert((track.to_owned(), seq.parse().expect("seq")));
        ResponseTemplate::new(200).set_body_json(serde_json::json!({ "status": "acknowledged" }))
    }
}

struct ListingRespond(Arc<Mutex<ServerState>>);

impl Respond for ListingRespond {
    fn respond(&self, _: &Request) -> ResponseTemplate {
        let state = self.0.lock().expect("state");
        let mut tracks: BTreeMap<String, Vec<u64>> = BTreeMap::new();
        for (track, seq) in &state.acknowledged {
            tracks.entry(track.clone()).or_default().push(*seq);
        }
        let tracks: serde_json::Map<String, serde_json::Value> = tracks
            .into_iter()
            .map(|(track, seqs)| {
                let through = *seqs.iter().max().expect("non-empty");
                let missing: Vec<u64> = (0..through).filter(|s| !seqs.contains(s)).collect();
                (
                    track,
                    serde_json::json!({ "acknowledged_through": through, "missing": missing }),
                )
            })
            .collect();
        ResponseTemplate::new(200).set_body_json(serde_json::json!({ "tracks": tracks }))
    }
}
