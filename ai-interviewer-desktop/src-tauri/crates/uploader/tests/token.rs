//! A session token that can't be had (2026-11-25). On the owner's PC the leftover segments of
//! three interviews that belonged to other accounts asked for a token once per segment: about
//! 12 requests a second, until the API's per-IP limit refused the real interview's token too and
//! its page said "Something went wrong".

mod common;

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use common::{Fake, INTERVIEW, TempDir, fast_config, open_store, payload, segment};
use hv_api_client::{ApiClient, ApiError, Url};
use hv_security::SoftwareKey;
use hv_segment_store::Track;
use hv_uploader::{RecordingSession, TokenFuture, Uploader};

/// A session whose token is always refused with `status` and `code`, counting the asks.
struct Refused {
    api: ApiClient,
    asked: AtomicUsize,
    status: u16,
    code: &'static str,
}

impl RecordingSession for Refused {
    fn api(&self) -> &ApiClient {
        &self.api
    }

    fn token(&self) -> TokenFuture<'_> {
        self.asked.fetch_add(1, Ordering::SeqCst);
        let (status, code) = (self.status, self.code);
        Box::pin(async move {
            Err(ApiError::Problem {
                status,
                code: code.to_owned(),
                detail: None,
                retry_after: None,
                body: serde_json::Value::Null,
            })
        })
    }
}

fn refused(base: &str, status: u16, code: &'static str) -> Arc<Refused> {
    let base = Url::parse(&format!("{base}/api/v1")).expect("base url");
    let api = ApiClient::new(base, Arc::new(SoftwareKey::generate()), "test".into()).expect("api");
    Arc::new(Refused {
        api,
        asked: AtomicUsize::new(0),
        status,
        code,
    })
}

fn fifty_segments(store: &hv_segment_store::SegmentStore) {
    for seq in 0..50 {
        store
            .put(segment(Track::Screen(1), seq), &payload(seq, 1_000))
            .expect("put");
    }
}

#[tokio::test]
async fn an_interview_that_isnt_this_accounts_stops_after_one_ask() {
    let dir = TempDir::new();
    let store = open_store(dir.path());
    fifty_segments(&store);
    let fake = Fake::start().await;
    let session = refused(&fake.uri(), 404, "not-found");
    let uploader =
        Uploader::new(session.clone(), Arc::clone(&store), fast_config()).expect("uploader");

    let drained = tokio::time::timeout(Duration::from_secs(5), uploader.drain(INTERVIEW))
        .await
        .expect("the drain stops instead of retrying forever");

    assert!(
        drained.is_err(),
        "the interview isn't uploadable from this account"
    );
    let asked = session.asked.load(Ordering::SeqCst);
    assert!(asked <= 2, "asked for a token {asked} times");
    let left = store.pending(INTERVIEW).expect("pending").len();
    assert_eq!(left, 50, "the segments stay for the account that owns them");
}

#[tokio::test]
async fn a_token_refused_for_now_backs_off_the_whole_interview() {
    let dir = TempDir::new();
    let store = open_store(dir.path());
    fifty_segments(&store);
    let fake = Fake::start().await;
    let session = refused(&fake.uri(), 429, "rate-limited");
    let uploader =
        Uploader::new(session.clone(), Arc::clone(&store), fast_config()).expect("uploader");

    // Retried for good, so the drain is still waiting when the time is up.
    let waiting = tokio::time::timeout(Duration::from_millis(400), uploader.drain(INTERVIEW)).await;

    assert!(waiting.is_err(), "a refusal for now is retried");
    // One ask per backoff of the interview (5 ms doubling to 40 ms): about 12 in 400 ms. One
    // per segment would be at least 50.
    let asked = session.asked.load(Ordering::SeqCst);
    assert!(asked < 25, "asked for a token {asked} times");
}
