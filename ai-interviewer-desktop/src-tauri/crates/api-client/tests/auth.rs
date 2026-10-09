//! `candidate-auth.md`, field for field.

mod common;

use common::{problem, proof_of, server_and_client};
use hv_api_client::auth::{
    self, AppInfo, DeviceInfo, LoginOutcome, LoginRequest, OtpVerify, ReleaseStatus,
};
use serde_json::json;
use wiremock::matchers::{body_json, header, method, path, query_param};
use wiremock::{Mock, ResponseTemplate};

fn login_request() -> LoginRequest {
    LoginRequest {
        email: "asha@example.test".into(),
        password: "correct horse".into(),
        app: AppInfo {
            version: "1.4.0".into(),
            channel: "stable".into(),
            os: "Windows 11 26200".into(),
            arch: "x64".into(),
        },
        device: DeviceInfo {
            name: "ASHA-LAPTOP".into(),
        },
    }
}

pub fn signed_in_body() -> serde_json::Value {
    json!({
        "status": "ok",
        "access_token": "eyJ.access",
        "token_type": "DPoP",
        "expires_in": 600,
        "refresh_token": "rt_1",
        "refresh_expires_in": 28800,
        "candidate": { "id": "c-1", "name": "Asha Rao", "email": "asha@example.test", "locale": "en-IN" },
        "organization": { "id": "o-1", "name": "Acme", "support_email": "help@acme.example.test" },
        "interviews": [{
            "id": "i-1",
            "job_title": "Backend Engineer",
            "status": "invited",
            "starts_at": "2026-10-12T04:30:00Z",
            "expires_at": "2026-10-13T18:29:59Z",
            "duration_minutes": 45,
            "third_eye": "optional",
            "proctoring_level": "standard",
            "coding": true
        }]
    })
}

#[tokio::test]
async fn login_sends_the_contract_body_and_maps_ok() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/login"))
        .and(body_json(json!({
            "email": "asha@example.test",
            "password": "correct horse",
            "app": { "version": "1.4.0", "channel": "stable", "os": "Windows 11 26200", "arch": "x64" },
            "device": { "name": "ASHA-LAPTOP" }
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(signed_in_body()))
        .expect(1)
        .mount(&server)
        .await;

    let outcome = auth::login(&api, &login_request()).await.expect("login");
    let LoginOutcome::Ok(signed_in) = outcome else {
        panic!("expected ok, got {outcome:?}");
    };
    assert_eq!(signed_in.access_token, "eyJ.access");
    assert_eq!(signed_in.token_type, "DPoP");
    assert_eq!(signed_in.expires_in, 600);
    assert_eq!(signed_in.refresh_token, "rt_1");
    assert_eq!(signed_in.refresh_expires_in, 28800);
    assert_eq!(signed_in.candidate.name, "Asha Rao");
    assert_eq!(signed_in.candidate.locale, "en-IN");
    assert_eq!(
        signed_in.organization.support_email,
        "help@acme.example.test"
    );
    let interview = &signed_in.interviews[0];
    assert_eq!(interview.id, "i-1");
    assert_eq!(interview.job_title, "Backend Engineer");
    assert_eq!(interview.status, "invited");
    assert_eq!(interview.starts_at, "2026-10-12T04:30:00Z");
    assert_eq!(interview.expires_at, "2026-10-13T18:29:59Z");
    assert_eq!(interview.duration_minutes, 45);
    assert_eq!(interview.third_eye, "optional");
    assert_eq!(interview.proctoring_level, "standard");
    assert!(interview.coding);

    // Tokens never show up in debug output.
    let debug = format!("{signed_in:?} {:?}", login_request());
    assert!(
        !debug.contains("eyJ.access") && !debug.contains("rt_1"),
        "{debug}"
    );
    assert!(!debug.contains("correct horse"), "{debug}");

    // Sign-in has a proof but no access token.
    let requests = server.received_requests().await.expect("recorded");
    assert!(requests[0].headers.get("Authorization").is_none());
    assert_eq!(proof_of(&requests[0]).claims.ath, None);
}

#[tokio::test]
async fn login_maps_otp_required() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/login"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "status": "otp_required",
            "challenge_id": "ch-1",
            "sent_to": "a***@example.test",
            "expires_in": 600
        })))
        .mount(&server)
        .await;

    let outcome = auth::login(&api, &login_request()).await.expect("login");
    let LoginOutcome::OtpRequired(challenge) = outcome else {
        panic!("expected otp_required, got {outcome:?}");
    };
    assert_eq!(challenge.challenge_id, "ch-1");
    assert_eq!(challenge.sent_to, "a***@example.test");
    assert_eq!(challenge.expires_in, 600);
}

#[tokio::test]
async fn login_failures_are_problems() {
    let (server, api) = server_and_client().await;
    let mut body = problem(426, "app-update-required");
    body["minimum_version"] = json!("1.5.0");
    body["download_url"] = json!("https://downloads.example.test/x");
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/login"))
        .respond_with(ResponseTemplate::new(426).set_body_json(body))
        .mount(&server)
        .await;

    let error = auth::login(&api, &login_request()).await.expect_err("426");
    assert_eq!(error.code(), "app-update-required");
    let hv_api_client::ApiError::Problem { body, .. } = error else {
        panic!("problem");
    };
    assert_eq!(body["minimum_version"], "1.5.0");
}

#[tokio::test]
async fn verify_and_resend_codes() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/otp/verify"))
        .and(body_json(
            json!({ "challenge_id": "ch-1", "code": "123456" }),
        ))
        .respond_with(ResponseTemplate::new(200).set_body_json(signed_in_body()))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/otp/resend"))
        .and(body_json(json!({ "challenge_id": "ch-1" })))
        .respond_with(ResponseTemplate::new(202))
        .expect(1)
        .mount(&server)
        .await;

    let outcome = auth::verify_otp(
        &api,
        &OtpVerify {
            challenge_id: "ch-1".into(),
            code: "123456".into(),
        },
    )
    .await
    .expect("verify");
    assert!(matches!(outcome, LoginOutcome::Ok(_)));
    auth::resend_otp(&api, "ch-1").await.expect("resend");
}

#[tokio::test]
async fn refresh_logout_and_me() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .and(body_json(json!({ "refresh_token": "rt_1" })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "access_token": "at_2",
            "token_type": "DPoP",
            "expires_in": 600,
            "refresh_token": "rt_2",
            "refresh_expires_in": 28000
        })))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/logout"))
        .and(header("Authorization", "DPoP at_2"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&server)
        .await;
    let mut me = signed_in_body();
    let me = json!({
        "candidate": me["candidate"].take(),
        "organization": me["organization"].take(),
        "interviews": me["interviews"].take(),
    });
    Mock::given(method("GET"))
        .and(path("/api/v1/candidate-auth/me"))
        .and(header("Authorization", "DPoP at_2"))
        .respond_with(ResponseTemplate::new(200).set_body_json(me))
        .expect(1)
        .mount(&server)
        .await;

    let pair = auth::refresh(&api, "rt_1").await.expect("refresh");
    assert_eq!(pair.access_token, "at_2");
    assert_eq!(pair.token_type, "DPoP");
    assert_eq!(pair.expires_in, 600);
    assert_eq!(pair.refresh_token, "rt_2");
    assert_eq!(pair.refresh_expires_in, 28000);

    let me = auth::me(&api, "at_2").await.expect("me");
    assert_eq!(me.candidate.email, "asha@example.test");
    assert_eq!(me.organization.name, "Acme");
    assert_eq!(me.interviews.len(), 1);

    auth::logout(&api, "at_2").await.expect("logout");

    let requests = server.received_requests().await.expect("recorded");
    let logout = requests
        .iter()
        .find(|r| r.url.path().ends_with("/logout"))
        .expect("logout request");
    assert_eq!(
        proof_of(logout).claims.ath.as_deref(),
        Some(hv_security::dpop::access_token_hash("at_2").as_str())
    );
}

#[tokio::test]
async fn session_token_for_an_interview() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/interviews/i-1/session-token"))
        .and(header("Authorization", "DPoP at_1"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "session_token": "eyJ.session",
            "token_type": "DPoP",
            "expires_at": "2026-10-12T05:30:00Z",
            "interview": {
                "id": "i-1",
                "status": "invited",
                "starts_at": "2026-10-12T04:30:00Z",
                "expires_at": "2026-10-13T18:29:59Z",
                "duration_minutes": 45
            }
        })))
        .expect(1)
        .mount(&server)
        .await;

    let token = auth::session_token(&api, "at_1", "i-1")
        .await
        .expect("session token");
    assert_eq!(token.session_token, "eyJ.session");
    assert_eq!(token.token_type, "DPoP");
    assert_eq!(token.expires_at, "2026-10-12T05:30:00Z");
    assert_eq!(token.interview.id, "i-1");
    assert_eq!(token.interview.duration_minutes, 45);
    assert!(!format!("{token:?}").contains("eyJ.session"));
}

#[tokio::test]
async fn interview_ids_are_escaped_in_the_path() {
    let (server, api) = server_and_client().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(404).set_body_json(problem(404, "not-found")))
        .mount(&server)
        .await;
    let _ = auth::session_token(&api, "at_1", "../../evil?x").await;
    let requests = server.received_requests().await.expect("recorded");
    assert_eq!(
        requests[0].url.path(),
        "/api/v1/candidate-auth/interviews/..%2F..%2Fevil%3Fx/session-token"
    );
    assert_eq!(requests[0].url.query(), None);
}

#[tokio::test]
async fn release_check() {
    let (server, api) = server_and_client().await;
    Mock::given(method("GET"))
        .and(path("/api/v1/desktop/releases/check"))
        .and(query_param("version", "1.4.0"))
        .and(query_param("channel", "stable"))
        .and(query_param("arch", "x64"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "status": "update-required",
            "latest": { "version": "1.5.0", "notes": "Fixes", "published_at": "2026-10-14T00:00:00Z" },
            "minimum_version": "1.5.0",
            "download_url": "https://downloads.hirevion.localhost/x"
        })))
        .expect(1)
        .mount(&server)
        .await;

    let check = auth::release_check(&api, "1.4.0", "stable", "x64")
        .await
        .expect("check");
    assert_eq!(check.status, ReleaseStatus::UpdateRequired);
    let latest = check.latest.expect("latest");
    assert_eq!(latest.version, "1.5.0");
    assert_eq!(latest.notes, "Fixes");
    assert_eq!(latest.published_at, "2026-10-14T00:00:00Z");
    assert_eq!(check.minimum_version, "1.5.0");
    assert_eq!(
        check.download_url.as_deref(),
        Some("https://downloads.hirevion.localhost/x")
    );

    // The proof lets the server place this device in a rollout.
    let requests = server.received_requests().await.expect("recorded");
    assert!(requests[0].headers.get("DPoP").is_some());
}

#[test]
fn release_statuses_use_the_contract_spelling() {
    for (text, status) in [
        ("ok", ReleaseStatus::Ok),
        ("update-available", ReleaseStatus::UpdateAvailable),
        ("update-required", ReleaseStatus::UpdateRequired),
    ] {
        let parsed: ReleaseStatus = serde_json::from_value(json!(text)).expect("parse");
        assert_eq!(parsed, status);
    }
}
