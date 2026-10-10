//! Chaos: a kill mid-upload, a network outage and flaky servers lose no acknowledged segment
//! and at most the one segment in flight (here: none, because the in-flight one is retried).

mod common;

use std::sync::Arc;
use std::time::Duration;

use common::{Fake, INTERVIEW, TempDir, drain_events, open_store, payload, segment, uploader};
use hv_segment_store::{SegmentState, SegmentStore, Track};
use hv_uploader::UploadEvent;
use wiremock::matchers::{method, path_regex};
use wiremock::{Mock, MockServer, ResponseTemplate};

const DRAIN: Duration = Duration::from_secs(15);

fn store_three(store: &SegmentStore) -> Vec<i64> {
    (0..3)
        .map(|seq| {
            store
                .put(segment(Track::Screen(1), seq), &payload(seq, 50_000))
                .expect("put")
                .id
        })
        .collect()
}

#[tokio::test]
async fn a_kill_mid_upload_loses_nothing() {
    let dir = TempDir::new();
    let ids = {
        let store = open_store(dir.path());
        let ids = store_three(&store);
        // The first server answers the URL request but its blob store hangs.
        let hung = Fake::start().await;
        Mock::given(method("PUT"))
            .and(path_regex("^/blob/"))
            .respond_with(ResponseTemplate::new(201).set_delay(Duration::from_secs(30)))
            .with_priority(1)
            .mount(&hung.server)
            .await;
        let uploader = uploader(&hung.uri(), &store);
        let task = tokio::spawn({
            let uploader = Arc::clone(&uploader);
            async move { uploader.drain(INTERVIEW).await }
        });
        tokio::time::timeout(Duration::from_secs(5), async {
            while hung.requests("PUT", "/blob/").await.is_empty() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("an upload started");
        task.abort(); // the app is killed mid-upload
        let _ = task.await;

        let row = store.get(ids[0]).expect("get").expect("row");
        assert_eq!(row.state, SegmentState::Uploading);
        assert!(store.segment_path(&row).exists());
        ids
    };

    // The next launch.
    let (reopened, recovery) = SegmentStore::open(
        dir.path().join("segments"),
        hv_security::Vault::new(dir.path().join("vault")),
    )
    .expect("reopen");
    assert_eq!(recovery.uploads_reset, 1);
    let store = Arc::new(reopened);
    let fake = Fake::start().await;
    let uploader = uploader(&fake.uri(), &store);
    tokio::time::timeout(DRAIN, uploader.drain(INTERVIEW))
        .await
        .expect("in time")
        .expect("drain");

    for id in ids {
        let row = store.get(id).expect("get").expect("row");
        assert_eq!(row.state, SegmentState::Purged, "segment {}", row.seq);
    }
    assert_eq!(fake.with(|s| s.acknowledged.len()), 3);
}

#[tokio::test]
async fn a_network_outage_is_ridden_out() {
    // Reserve a port, then leave it closed: every request is refused, as when offline.
    let port = {
        let probe = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
        probe.local_addr().expect("addr").port()
    };
    let base = format!("http://127.0.0.1:{port}");
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let ids = store_three(&store);
    let uploader = uploader(&base, &store);
    let mut events = uploader.subscribe();
    let task = tokio::spawn({
        let uploader = Arc::clone(&uploader);
        async move { uploader.drain(INTERVIEW).await }
    });

    // Windows takes a second or two to report a refused loopback connection.
    let mut offline = Vec::new();
    let network_retries = |seen: &[UploadEvent]| {
        seen.iter()
            .filter(|e| matches!(e, UploadEvent::Retrying { code, .. } if code == "network"))
            .count()
    };
    tokio::time::timeout(Duration::from_secs(20), async {
        while network_retries(&offline) < 2 {
            offline.extend(drain_events(&mut events));
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap_or_else(|_| panic!("no network retries: {offline:?}"));
    assert!(!task.is_finished());
    for &id in &ids {
        assert!(store.get(id).expect("get").expect("row").state.is_pending());
    }

    // The network comes back.
    let listener = std::net::TcpListener::bind(("127.0.0.1", port)).expect("rebind");
    let fake = Fake::on(MockServer::builder().listener(listener).start().await).await;
    tokio::time::timeout(DRAIN, task)
        .await
        .expect("in time")
        .expect("task")
        .expect("drain");

    for id in ids {
        assert_eq!(
            store.get(id).expect("get").expect("row").state,
            SegmentState::Purged
        );
    }
    assert_eq!(fake.with(|s| s.acknowledged.len()), 3);
}

#[tokio::test]
async fn flaky_servers_are_retried_with_backoff() {
    let fake = Fake::start().await;
    fake.with(|s| {
        s.fail_urls = 3;
        s.fail_puts = 2;
        s.fail_acks = 2;
    });
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let ids = store_three(&store);
    let uploader = uploader(&fake.uri(), &store);

    tokio::time::timeout(DRAIN, uploader.drain(INTERVIEW))
        .await
        .expect("in time")
        .expect("drain");

    let attempts: u32 = ids
        .iter()
        .map(|&id| store.get(id).expect("get").expect("row").attempts)
        .sum();
    assert_eq!(attempts, 7, "every failure was counted once");
    for id in ids {
        assert_eq!(
            store.get(id).expect("get").expect("row").state,
            SegmentState::Purged
        );
    }
}

#[tokio::test]
async fn a_crash_after_the_server_acknowledged_is_settled_by_recovery() {
    let fake = Fake::start().await;
    fake.with(|s| s.acknowledged.insert(("screen-1".into(), 0)));
    let dir = TempDir::new();
    let store = open_store(dir.path());
    let stored = store
        .put(segment(Track::Screen(1), 0), b"bytes")
        .expect("put");
    // The app sent the ack and died before recording the answer.
    store.enqueue(stored.id).expect("queue");
    store.start_upload(stored.id, "screen-1-0").expect("upload");
    store
        .transition(stored.id, SegmentState::Uploaded)
        .expect("uploaded");
    let uploader = uploader(&fake.uri(), &store);

    tokio::time::timeout(DRAIN, uploader.drain(INTERVIEW))
        .await
        .expect("in time")
        .expect("drain");

    assert_eq!(
        store.get(stored.id).expect("get").expect("row").state,
        SegmentState::Purged
    );
    assert!(fake.requests("PUT", "/blob/").await.is_empty());
}
