//! The DPoP-bound request pipeline: headers, nonces, problems and server time.

mod common;

use common::{ProofNonce, USER_AGENT, problem, proof_of, server_and_client};
use hv_api_client::{ApiError, ClockSample, Method};
use hv_security::dpop;
use serde_json::json;
use wiremock::matchers::{body_json, header, method, path, query_param};
use wiremock::{Mock, ResponseTemplate};

#[tokio::test]
async fn every_request_carries_a_dpop_proof_and_the_dpop_authorization() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/things"))
        .and(header("Authorization", "DPoP token-abc"))
        .and(header("User-Agent", USER_AGENT))
        .and(body_json(json!({ "a": 1 })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "ok": true })))
        .expect(1)
        .mount(&server)
        .await;

    let answer: serde_json::Value = api
        .send(
            Method::POST,
            "things?page=2",
            Some(&json!({ "a": 1 })),
            Some("token-abc"),
        )
        .await
        .expect("send");
    assert_eq!(answer, json!({ "ok": true }));

    let requests = server.received_requests().await.expect("recorded");
    let proof = proof_of(&requests[0]);
    assert_eq!(proof.claims.htm, "POST");
    assert_eq!(proof.claims.htu, format!("{}/api/v1/things", server.uri()));
    assert_eq!(
        proof.claims.ath.as_deref(),
        Some(dpop::access_token_hash("token-abc").as_str())
    );
    assert_eq!(proof.claims.nonce, None);
    assert_eq!(proof.header.jwk, api.signer().public_jwk());
    // iat is close to now.
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("time")
        .as_secs() as i64;
    assert!((proof.claims.iat - now).abs() <= 5);
}

#[tokio::test]
async fn unauthenticated_requests_still_carry_a_proof_without_ath() {
    let (server, api) = server_and_client().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/open"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&server)
        .await;

    api.send_no_content::<()>(Method::GET, "open", None, None)
        .await
        .expect("send");

    let requests = server.received_requests().await.expect("recorded");
    assert!(requests[0].headers.get("Authorization").is_none());
    let proof = proof_of(&requests[0]);
    assert_eq!(proof.claims.htm, "GET");
    assert_eq!(proof.claims.ath, None);
}

#[tokio::test]
async fn a_nonce_challenge_is_retried_once_and_the_nonce_is_remembered() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/things"))
        .and(ProofNonce(Some("n-1")))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({ "ok": 1 })))
        .with_priority(1)
        .expect(2)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/things"))
        .and(ProofNonce(None))
        .respond_with(
            ResponseTemplate::new(401)
                .insert_header("DPoP-Nonce", "n-1")
                .set_body_json(problem(401, "use-dpop-nonce")),
        )
        .expect(1)
        .mount(&server)
        .await;

    let first: serde_json::Value = api
        .send(Method::POST, "things", Some(&json!({})), None)
        .await
        .expect("retried with the nonce");
    assert_eq!(first, json!({ "ok": 1 }));

    // The next request uses the remembered nonce straight away: no second challenge.
    let second: serde_json::Value = api
        .send(Method::POST, "things", Some(&json!({})), None)
        .await
        .expect("second");
    assert_eq!(second, json!({ "ok": 1 }));

    let requests = server.received_requests().await.expect("recorded");
    assert_eq!(requests.len(), 3);
    // The retry resends the same body with a fresh proof.
    assert_eq!(requests[0].body, requests[1].body);
    assert_ne!(
        proof_of(&requests[0]).claims.jti,
        proof_of(&requests[1]).claims.jti
    );
}

#[tokio::test]
async fn the_nonce_retry_happens_only_once() {
    let (server, api) = server_and_client().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/things"))
        .respond_with(
            ResponseTemplate::new(401)
                .insert_header("DPoP-Nonce", "always-new")
                .set_body_json(problem(401, "use-dpop-nonce")),
        )
        .expect(2)
        .mount(&server)
        .await;

    let error = api
        .send::<(), serde_json::Value>(Method::GET, "things", None, None)
        .await
        .expect_err("gives up after one retry");
    assert_eq!(error.code(), "use-dpop-nonce");
    assert_eq!(error.status(), Some(401));
}

#[tokio::test]
async fn a_nonce_problem_without_a_nonce_header_is_not_retried() {
    let (server, api) = server_and_client().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/things"))
        .respond_with(ResponseTemplate::new(401).set_body_json(problem(401, "use-dpop-nonce")))
        .expect(1)
        .mount(&server)
        .await;

    let error = api
        .send::<(), serde_json::Value>(Method::GET, "things", None, None)
        .await
        .expect_err("not retried");
    assert_eq!(error.code(), "use-dpop-nonce");
}

#[tokio::test]
async fn problems_are_parsed_with_retry_after_and_the_raw_body() {
    let (server, api) = server_and_client().await;
    let body = json!({
        "type": "https://hirevion.example.test/problems/account-locked",
        "title": "Account locked",
        "status": 423,
        "detail": "Too many attempts.",
        "code": "account-locked",
        "extra": 7,
    });
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/login"))
        .respond_with(
            ResponseTemplate::new(423)
                .insert_header("Retry-After", "120")
                .insert_header("Content-Type", "application/problem+json")
                .set_body_json(body.clone()),
        )
        .mount(&server)
        .await;

    let error = api
        .send::<_, serde_json::Value>(Method::POST, "candidate-auth/login", Some(&json!({})), None)
        .await
        .expect_err("problem");
    match error {
        ApiError::Problem {
            status,
            code,
            detail,
            retry_after,
            body: raw,
        } => {
            assert_eq!(status, 423);
            assert_eq!(code, "account-locked");
            assert_eq!(detail.as_deref(), Some("Too many attempts."));
            assert_eq!(retry_after, Some(120));
            assert_eq!(raw, body);
        }
        other => panic!("expected a problem, got {other:?}"),
    }
}

#[tokio::test]
async fn a_non_problem_error_body_still_gives_a_code() {
    let (server, api) = server_and_client().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/things"))
        .respond_with(ResponseTemplate::new(502).set_body_string("<html>Bad gateway</html>"))
        .mount(&server)
        .await;

    let error = api
        .send::<(), serde_json::Value>(Method::GET, "things", None, None)
        .await
        .expect_err("502");
    assert_eq!(error.code(), "http-502");
    assert_eq!(error.status(), Some(502));
    match error {
        ApiError::Problem {
            body,
            detail,
            retry_after,
            ..
        } => {
            assert_eq!(body, json!("<html>Bad gateway</html>"));
            assert_eq!(detail, None);
            assert_eq!(retry_after, None);
        }
        other => panic!("expected a problem, got {other:?}"),
    }
}

#[tokio::test]
async fn an_unexpected_success_body_is_a_decode_error() {
    let (server, api) = server_and_client().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/things"))
        .respond_with(ResponseTemplate::new(200).set_body_string("not json"))
        .mount(&server)
        .await;

    let error = api
        .send::<(), serde_json::Value>(Method::GET, "things", None, None)
        .await
        .expect_err("decode");
    assert!(matches!(error, ApiError::Decode(_)), "{error:?}");
    assert_eq!(error.code(), "decode");
}

#[tokio::test]
async fn an_unreachable_server_is_a_network_error() {
    // A port that was free a moment ago and has nothing listening now. (A dropped MockServer
    // goes back to wiremock's pool and keeps answering.)
    let port = std::net::TcpListener::bind("127.0.0.1:0")
        .expect("bind")
        .local_addr()
        .expect("addr")
        .port();
    let base = hv_api_client::Url::parse(&format!("http://127.0.0.1:{port}/api/v1")).expect("url");
    let api = hv_api_client::ApiClient::new(
        base,
        std::sync::Arc::new(hv_security::SoftwareKey::generate()),
        USER_AGENT.into(),
    )
    .expect("client");
    let error = api
        .send::<(), serde_json::Value>(Method::GET, "things", None, None)
        .await
        .expect_err("network");
    assert!(matches!(error, ApiError::Network(_)), "{error:?}");
}

#[tokio::test]
async fn paths_cannot_leave_the_api_origin() {
    let (_server, api) = server_and_client().await;
    for path in [
        "https://evil.example.test/steal",
        "//evil.example.test/x",
        "/api/v2/other",
        "../../admin",
        "%2e%2e/%2e%2e/admin",
    ] {
        let error = api
            .send::<(), serde_json::Value>(Method::GET, path, None, Some("secret"))
            .await
            .expect_err("refused");
        assert!(matches!(error, ApiError::Security(_)), "{path}: {error:?}");
    }
}

#[tokio::test]
async fn query_strings_are_sent_but_not_signed() {
    let (server, api) = server_and_client().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/search"))
        .and(query_param("q", "a b"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!([])))
        .expect(1)
        .mount(&server)
        .await;
    let _: serde_json::Value = api
        .send::<(), _>(Method::GET, "search?q=a%20b", None, None)
        .await
        .expect("send");
    let requests = server.received_requests().await.expect("recorded");
    assert_eq!(
        proof_of(&requests[0]).claims.htu,
        format!("{}/api/v1/search", server.uri())
    );
}

#[test]
fn clock_offset_is_the_ntp_estimate() {
    // Local clock 5 s behind: sent at 1000 local, the server received at 6010 and answered at
    // 6020 server time, the answer arrived at 1040 local.
    let sample = ClockSample::from_timestamps(1000, 6010, 6020, 1040);
    assert_eq!(sample.round_trip_ms, 30);
    assert_eq!(sample.offset_ms, 4995);

    // A local clock ahead gives a negative offset.
    let sample = ClockSample::from_timestamps(10_000, 7_005, 7_005, 10_010);
    assert_eq!(sample.round_trip_ms, 10);
    assert_eq!(sample.offset_ms, -3000);
}

#[tokio::test]
async fn sync_clock_reads_server_time_and_offsets_proofs() {
    let (server, api) = server_and_client().await;
    let local_now = now_ms();
    let server_now = local_now + 120_000; // the server is two minutes ahead
    Mock::given(method("GET"))
        .and(path("/api/v1/time"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "received_at_ms": server_now,
            "sent_at_ms": server_now,
        })))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .and(path("/api/v1/things"))
        .respond_with(ResponseTemplate::new(204))
        .mount(&server)
        .await;

    assert_eq!(api.clock(), None);
    let sample = api.sync_clock().await.expect("sync");
    assert!((sample.offset_ms - 120_000).abs() < 2_000, "{sample:?}");
    assert!(sample.round_trip_ms >= 0);
    assert_eq!(api.clock(), Some(sample));
    assert!((api.server_now_ms() - (now_ms() + 120_000)).abs() < 2_000);

    // Proofs are stamped in server time.
    api.send_no_content::<()>(Method::GET, "things", None, None)
        .await
        .expect("send");
    let requests = server.received_requests().await.expect("recorded");
    let proof = proof_of(requests.last().expect("request"));
    assert!((proof.claims.iat * 1000 - server_now).abs() < 3_000);
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("time")
        .as_millis() as i64
}

#[tokio::test]
async fn send_value_returns_the_body_or_null_when_there_is_none() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/things/accepted"))
        .respond_with(ResponseTemplate::new(202))
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/things/answered"))
        .respond_with(
            ResponseTemplate::new(202).set_body_json(json!({ "state": { "voice": "thinking" } })),
        )
        .mount(&server)
        .await;

    let empty = api
        .send_value(Method::POST, "things/accepted", Some(&json!({})), None)
        .await
        .expect("an empty answer");
    assert_eq!(empty, serde_json::Value::Null);
    let answered = api
        .send_value(Method::POST, "things/answered", None, None)
        .await
        .expect("a JSON answer");
    assert_eq!(answered["state"]["voice"], "thinking");
}
