mod common;

use std::time::{Duration, Instant};

use common::{
    Fake, INTERVIEW, TOKEN, TempDir, drain_events, open_store, payload, segment, uploader,
};
use hv_segment_store::{SegmentState, Track, sha256_hex};
use hv_uploader::UploadEvent;

const DRAIN: Duration = Duration::from_secs(10);

async fn drain(uploader: &hv_uploader::Uploader) {
    tokio::time::timeout(DRAIN, uploader.drain(INTERVIEW))
        .await
        .expect("drained in time")
        .expect("drain");
}

#[tokio::test]
async fn uploads_a_segment_and_deletes_it_only_after_the_ack() {
    let fake = Fake::start().await;
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let plain = payload(0, 200_000);
    let stored = store
        .put(segment(Track::Screen(1), 0), &plain)
        .expect("put");
    let file = store.segment_path(&stored);
    let uploader = uploader(&fake.uri(), &store);
    let mut events = uploader.subscribe();

    drain(&uploader).await;

    // The URL request: DPoP-bound, with the contract's fields.
    let urls = fake.requests("POST", "/api/v1/recordings/segments").await;
    let url_request = urls
        .iter()
        .find(|r| r.url.path() == "/api/v1/recordings/segments")
        .expect("URL requested");
    assert_eq!(
        url_request.headers.get("authorization").expect("auth"),
        &format!("DPoP {TOKEN}")
    );
    assert!(url_request.headers.get("dpop").is_some());
    let body: serde_json::Value = serde_json::from_slice(&url_request.body).expect("json");
    assert_eq!(
        body,
        serde_json::json!({
            "interview_id": INTERVIEW,
            "track": "screen-1",
            "seq": 0,
            "started_at": "2023-11-14T22:13:20.123Z",
            "duration_ms": 10_000,
            "bytes": 200_000,
            "sha256": sha256_hex(&plain),
            "container": "mp4",
            "codec": "h264",
        })
    );

    // The PUT: the plaintext, the server's headers, a length, and no token.
    let puts = fake.requests("PUT", "/blob/").await;
    assert_eq!(puts.len(), 1);
    let put = &puts[0];
    assert_eq!(put.url.query(), Some("sv=2025&sig=write-only"));
    assert_eq!(put.body, plain);
    assert_eq!(
        put.headers.get("x-ms-blob-type").expect("blob type"),
        "BlockBlob"
    );
    assert_eq!(put.headers.get("content-type").expect("type"), "video/mp4");
    assert_eq!(put.headers.get("content-length").expect("length"), "200000");
    assert!(put.headers.get("authorization").is_none());
    assert!(put.headers.get("dpop").is_none());

    // The ack carries the plaintext hash; only then is the file gone.
    let acks = fake
        .requests("POST", "/api/v1/recordings/segments/screen-1-0/ack")
        .await;
    assert_eq!(acks.len(), 1);
    let ack: serde_json::Value = serde_json::from_slice(&acks[0].body).expect("json");
    assert_eq!(ack, serde_json::json!({ "sha256": sha256_hex(&plain) }));
    let row = store.get(stored.id).expect("get").expect("row");
    assert_eq!(row.state, SegmentState::Purged);
    assert!(!file.exists());
    assert!(
        drain_events(&mut events).contains(&UploadEvent::Acknowledged {
            track: Track::Screen(1),
            seq: 0
        })
    );
}

#[tokio::test]
async fn an_already_acknowledged_segment_is_deleted_without_uploading() {
    let fake = Fake::start().await;
    fake.with(|s| s.acknowledged.insert(("camera".into(), 3)));
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let stored = store
        .put(segment(Track::Camera, 3), b"camera")
        .expect("put");
    let uploader = uploader(&fake.uri(), &store);

    drain(&uploader).await;

    assert!(fake.requests("PUT", "/blob/").await.is_empty());
    let row = store.get(stored.id).expect("get").expect("row");
    assert_eq!(row.state, SegmentState::Purged);
}

#[tokio::test]
async fn a_hash_mismatch_uploads_again_with_a_new_url() {
    let fake = Fake::start().await;
    fake.with(|s| s.corrupt_next = 1);
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let stored = store
        .put(segment(Track::Mic, 0), &payload(1, 5_000))
        .expect("put");
    let uploader = uploader(&fake.uri(), &store);
    let mut events = uploader.subscribe();

    drain(&uploader).await;

    assert_eq!(fake.requests("PUT", "/blob/").await.len(), 2);
    let row = store.get(stored.id).expect("get").expect("row");
    assert_eq!(row.state, SegmentState::Purged);
    assert_eq!(row.attempts, 1);
    assert_eq!(row.last_error.as_deref(), Some("hash-mismatch"));
    assert!(drain_events(&mut events).iter().any(|e| matches!(
        e,
        UploadEvent::Retrying { code, .. } if code == "hash-mismatch"
    )));
}

#[tokio::test]
async fn a_missing_blob_uploads_again() {
    let fake = Fake::start().await;
    fake.with(|s| s.lose_next = 1);
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let stored = store
        .put(segment(Track::Camera, 0), b"frames")
        .expect("put");
    let uploader = uploader(&fake.uri(), &store);

    drain(&uploader).await;

    assert_eq!(fake.requests("PUT", "/blob/").await.len(), 2);
    let row = store.get(stored.id).expect("get").expect("row");
    assert_eq!(row.state, SegmentState::Purged);
    assert_eq!(row.last_error.as_deref(), Some("blob-missing"));
}

#[tokio::test]
async fn a_failing_ack_keeps_the_local_file_and_retries_only_the_ack() {
    let fake = Fake::start().await;
    fake.with(|s| s.fail_acks = usize::MAX);
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let stored = store
        .put(segment(Track::Screen(1), 0), b"bytes")
        .expect("put");
    let file = store.segment_path(&stored);
    let uploader = uploader(&fake.uri(), &store);

    // Generous: CI runners are slow; the assertion is that the ack is retried, not how fast.
    let drained =
        tokio::time::timeout(Duration::from_millis(3_000), uploader.drain(INTERVIEW)).await;

    assert!(drained.is_err(), "can't finish without an ack");
    let row = store.get(stored.id).expect("get").expect("row");
    assert_eq!(row.state, SegmentState::Uploaded);
    assert!(row.attempts >= 2, "ack retried: {}", row.attempts);
    assert!(file.exists(), "never deleted before the ack");
    assert_eq!(
        fake.requests("PUT", "/blob/").await.len(),
        1,
        "no re-upload"
    );
}

#[tokio::test]
async fn a_track_the_interview_does_not_record_is_stopped() {
    let fake = Fake::start().await;
    fake.with(|s| s.not_recorded.insert("camera".into()));
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let first = store.put(segment(Track::Camera, 0), b"zero").expect("put");
    let second = store.put(segment(Track::Camera, 1), b"one").expect("put");
    let screen = store
        .put(segment(Track::Screen(1), 0), b"screen")
        .expect("put");
    let uploader = uploader(&fake.uri(), &store);
    let mut events = uploader.subscribe();

    drain(&uploader).await;

    let state = |id| store.get(id).expect("get").expect("row").state;
    assert_eq!(state(first.id), SegmentState::Rejected);
    assert_eq!(state(second.id), SegmentState::Rejected);
    assert_eq!(state(screen.id), SegmentState::Purged);
    let camera_requests = fake
        .requests("POST", "/api/v1/recordings/segments")
        .await
        .into_iter()
        .filter(|r| r.url.path() == "/api/v1/recordings/segments")
        .filter(|r| String::from_utf8_lossy(&r.body).contains("\"camera\""))
        .count();
    assert_eq!(camera_requests, 1, "not retried, and the track is stopped");
    assert!(
        drain_events(&mut events).contains(&UploadEvent::TrackRefused {
            track: Track::Camera
        })
    );
    // Later segments of a refused track are rejected without asking again.
    let later = store.put(segment(Track::Camera, 2), b"two").expect("put");
    drain(&uploader).await;
    assert_eq!(state(later.id), SegmentState::Rejected);
}

#[tokio::test]
async fn a_segment_that_is_too_large_is_rejected() {
    let fake = Fake::start().await;
    fake.with(|s| s.max_bytes = Some(10));
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let stored = store
        .put(segment(Track::Screen(1), 0), &payload(0, 11))
        .expect("put");
    let uploader = uploader(&fake.uri(), &store);
    let mut events = uploader.subscribe();

    drain(&uploader).await;

    let row = store.get(stored.id).expect("get").expect("row");
    assert_eq!(row.state, SegmentState::Rejected);
    assert_eq!(row.last_error.as_deref(), Some("segment-too-large"));
    assert!(drain_events(&mut events).iter().any(|e| matches!(
        e,
        UploadEvent::Rejected { code, .. } if code == "segment-too-large"
    )));
}

#[tokio::test]
async fn recovery_skips_what_the_server_already_holds() {
    let fake = Fake::start().await;
    fake.with(|s| {
        // acknowledged_through 2, missing [1]
        s.acknowledged.insert(("screen-1".into(), 0));
        s.acknowledged.insert(("screen-1".into(), 2));
    });
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let ids: Vec<i64> = (0..4)
        .map(|seq| {
            store
                .put(segment(Track::Screen(1), seq), &payload(seq, 100))
                .expect("put")
                .id
        })
        .collect();
    let uploader = uploader(&fake.uri(), &store);

    let summary = uploader.recover(INTERVIEW).await.expect("recover");
    assert_eq!(summary.already_acknowledged, 2);
    assert_eq!(summary.to_upload, 2);
    let state = |id| store.get(id).expect("get").expect("row").state;
    assert_eq!(state(ids[0]), SegmentState::Purged);
    assert_eq!(state(ids[2]), SegmentState::Purged);
    assert_eq!(state(ids[1]), SegmentState::Queued);

    drain(&uploader).await;

    let requested: Vec<u64> = fake
        .requests("POST", "/api/v1/recordings/segments")
        .await
        .into_iter()
        .filter(|r| r.url.path() == "/api/v1/recordings/segments")
        .map(|r| {
            serde_json::from_slice::<serde_json::Value>(&r.body).expect("json")["seq"]
                .as_u64()
                .expect("seq")
        })
        .collect();
    assert_eq!(requested, [1, 3]);
    assert!(ids.iter().all(|&id| state(id) == SegmentState::Purged));
}

#[tokio::test]
async fn an_insecure_upload_url_is_never_used() {
    let fake = Fake::start().await;
    fake.with(|s| s.upload_origin = Some("http://blob.example.test".into()));
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let stored = store
        .put(segment(Track::Screen(1), 0), b"bytes")
        .expect("put");
    let uploader = uploader(&fake.uri(), &store);

    let drained = tokio::time::timeout(Duration::from_millis(200), uploader.drain(INTERVIEW)).await;

    assert!(drained.is_err(), "nothing can be uploaded");
    let row = store.get(stored.id).expect("get").expect("row");
    assert_eq!(row.state, SegmentState::Queued);
    assert_eq!(row.last_error.as_deref(), Some("insecure-upload-url"));
    assert!(row.segment_id.is_none());
}

#[tokio::test]
async fn the_bandwidth_cap_paces_the_upload_and_can_be_lifted() {
    let fake = Fake::start().await;
    let dir = TempDir::new();
    let store = open_store(dir.path());
    store
        .put(segment(Track::Screen(1), 0), &payload(0, 100_000))
        .expect("put");
    let uploader = uploader(&fake.uri(), &store);
    uploader.bandwidth().set_limit(Some(100_000));

    let started = Instant::now();
    drain(&uploader).await;
    let capped = started.elapsed();
    // 100 kB at 100 kB/s with a 25 kB burst: at least 0.75 s.
    assert!(capped >= Duration::from_millis(700), "{capped:?}");

    uploader.bandwidth().set_limit(None);
    store
        .put(segment(Track::Screen(1), 1), &payload(1, 100_000))
        .expect("put");
    let started = Instant::now();
    drain(&uploader).await;
    let uncapped = started.elapsed();
    // Relative, not absolute: a slow CI runner still uploads faster without the cap.
    assert!(
        uncapped < capped,
        "uncapped {uncapped:?}, capped {capped:?}"
    );
}
