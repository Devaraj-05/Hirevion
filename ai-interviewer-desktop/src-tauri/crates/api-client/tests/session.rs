//! The session manager: tokens in memory, the refresh token in the vault, rotation and sign-out.

mod common;

use common::{TempDir, client_for, problem};
use hv_api_client::auth::{AppInfo, DeviceInfo, LoginOutcome, LoginRequest, OtpVerify};
use hv_api_client::{ApiError, REFRESH_TOKEN_KEY, SessionManager};
use hv_security::Vault;
use serde_json::json;
use wiremock::matchers::{body_json, header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn login_request() -> LoginRequest {
    LoginRequest {
        email: "asha@example.test".into(),
        password: "pw".into(),
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

fn signed_in(access: &str, expires_in: u64, refresh: &str) -> serde_json::Value {
    json!({
        "status": "ok",
        "access_token": access,
        "token_type": "DPoP",
        "expires_in": expires_in,
        "refresh_token": refresh,
        "refresh_expires_in": 28800,
        "candidate": { "id": "c-1", "name": "Asha Rao", "email": "asha@example.test", "locale": "en-IN" },
        "organization": { "id": "o-1", "name": "Acme", "support_email": "help@acme.example.test" },
        "interviews": []
    })
}

fn token_pair(access: &str, expires_in: u64, refresh: &str) -> serde_json::Value {
    json!({
        "access_token": access,
        "token_type": "DPoP",
        "expires_in": expires_in,
        "refresh_token": refresh,
        "refresh_expires_in": 28000
    })
}

async fn mount_login(server: &MockServer, access: &str, expires_in: u64, refresh: &str) {
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/login"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(signed_in(access, expires_in, refresh)),
        )
        .mount(server)
        .await;
}

fn stored(vault: &Vault) -> Option<String> {
    vault
        .get(REFRESH_TOKEN_KEY)
        .expect("vault")
        .map(|bytes| String::from_utf8(bytes).expect("utf-8"))
}

struct Fixture {
    server: MockServer,
    session: SessionManager,
    vault: Vault,
    _dir: TempDir,
}

async fn fixture() -> Fixture {
    let server = MockServer::start().await;
    let dir = TempDir::new();
    let vault = Vault::new(&dir.0);
    let session = SessionManager::new(client_for(&server), vault.clone());
    Fixture {
        server,
        session,
        vault,
        _dir: dir,
    }
}

#[tokio::test]
async fn sign_in_keeps_the_access_token_in_memory_and_the_refresh_token_in_the_vault() {
    let f = fixture().await;
    mount_login(&f.server, "at_1", 600, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .respond_with(ResponseTemplate::new(500))
        .expect(0)
        .mount(&f.server)
        .await;

    assert!(!f.session.has_saved_session());
    let outcome = f.session.sign_in(&login_request()).await.expect("sign in");
    assert!(matches!(outcome, LoginOutcome::Ok(_)));
    assert_eq!(stored(&f.vault).as_deref(), Some("rt_1"));
    assert!(f.session.has_saved_session());

    // Plenty of time left: no refresh.
    assert_eq!(f.session.access_token().await.expect("token"), "at_1");
}

#[tokio::test]
async fn an_otp_challenge_stores_nothing_until_the_code_is_verified() {
    let f = fixture().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/login"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "status": "otp_required", "challenge_id": "ch-1", "sent_to": "a***@example.test", "expires_in": 600
        })))
        .mount(&f.server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/otp/verify"))
        .respond_with(ResponseTemplate::new(200).set_body_json(signed_in("at_v", 600, "rt_v")))
        .mount(&f.server)
        .await;

    let outcome = f.session.sign_in(&login_request()).await.expect("sign in");
    assert!(matches!(outcome, LoginOutcome::OtpRequired(_)));
    assert_eq!(stored(&f.vault), None);
    assert!(matches!(
        f.session.access_token().await,
        Err(ApiError::SignedOut)
    ));

    f.session
        .verify_code(&OtpVerify {
            challenge_id: "ch-1".into(),
            code: "123456".into(),
        })
        .await
        .expect("verify");
    assert_eq!(stored(&f.vault).as_deref(), Some("rt_v"));
    assert_eq!(f.session.access_token().await.expect("token"), "at_v");
}

#[tokio::test]
async fn a_token_close_to_expiry_is_refreshed_and_the_rotated_refresh_token_is_stored() {
    let f = fixture().await;
    // 30 s left is under the 60 s margin.
    mount_login(&f.server, "at_1", 30, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .and(body_json(json!({ "refresh_token": "rt_1" })))
        .respond_with(ResponseTemplate::new(200).set_body_json(token_pair("at_2", 30, "rt_2")))
        .expect(1)
        .mount(&f.server)
        .await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .and(body_json(json!({ "refresh_token": "rt_2" })))
        .respond_with(ResponseTemplate::new(200).set_body_json(token_pair("at_3", 600, "rt_3")))
        .expect(1)
        .mount(&f.server)
        .await;

    f.session.sign_in(&login_request()).await.expect("sign in");

    assert_eq!(f.session.access_token().await.expect("token"), "at_2");
    assert_eq!(stored(&f.vault).as_deref(), Some("rt_2"));

    // The rotated refresh token is the one used next.
    assert_eq!(f.session.access_token().await.expect("token"), "at_3");
    assert_eq!(stored(&f.vault).as_deref(), Some("rt_3"));

    // Now there's time left: no more refreshes (the mocks' expect(1) checks this).
    assert_eq!(f.session.access_token().await.expect("token"), "at_3");
}

#[tokio::test]
async fn concurrent_callers_share_one_refresh() {
    let f = fixture().await;
    mount_login(&f.server, "at_1", 10, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(token_pair("at_2", 600, "rt_2"))
                .set_delay(std::time::Duration::from_millis(100)),
        )
        .expect(1)
        .mount(&f.server)
        .await;
    f.session.sign_in(&login_request()).await.expect("sign in");

    let (a, b, c) = tokio::join!(
        f.session.access_token(),
        f.session.access_token(),
        f.session.access_token()
    );
    for token in [a, b, c] {
        assert_eq!(token.expect("token"), "at_2");
    }
}

#[tokio::test]
async fn a_saved_session_resumes_from_the_vault() {
    let f = fixture().await;
    f.vault.put(REFRESH_TOKEN_KEY, b"rt_saved").expect("seed");
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .and(body_json(json!({ "refresh_token": "rt_saved" })))
        .respond_with(ResponseTemplate::new(200).set_body_json(token_pair("at_r", 600, "rt_next")))
        .expect(1)
        .mount(&f.server)
        .await;

    assert!(f.session.has_saved_session());
    assert_eq!(f.session.access_token().await.expect("token"), "at_r");
    assert_eq!(stored(&f.vault).as_deref(), Some("rt_next"));
}

#[tokio::test]
async fn a_reused_refresh_token_clears_the_session() {
    let f = fixture().await;
    mount_login(&f.server, "at_1", 5, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .respond_with(ResponseTemplate::new(401).set_body_json(problem(401, "refresh-reused")))
        .expect(1)
        .mount(&f.server)
        .await;

    f.session.sign_in(&login_request()).await.expect("sign in");
    let error = f.session.access_token().await.expect_err("reused");
    assert_eq!(error.code(), "refresh-reused");

    assert_eq!(stored(&f.vault), None);
    assert!(!f.session.has_saved_session());
    // Signed out now, without asking the server again.
    assert!(matches!(
        f.session.access_token().await,
        Err(ApiError::SignedOut)
    ));
}

#[tokio::test]
async fn an_invalid_refresh_token_clears_the_session() {
    let f = fixture().await;
    f.vault.put(REFRESH_TOKEN_KEY, b"rt_old").expect("seed");
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .respond_with(ResponseTemplate::new(401).set_body_json(problem(401, "refresh-invalid")))
        .mount(&f.server)
        .await;

    let error = f.session.access_token().await.expect_err("invalid");
    assert_eq!(error.code(), "refresh-invalid");
    assert_eq!(stored(&f.vault), None);
}

#[tokio::test]
async fn other_refresh_failures_keep_the_session() {
    let f = fixture().await;
    // Already expired: the refresh failure is all there is to report.
    mount_login(&f.server, "at_1", 0, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .respond_with(ResponseTemplate::new(426).set_body_json(problem(426, "app-update-required")))
        .mount(&f.server)
        .await;

    f.session.sign_in(&login_request()).await.expect("sign in");
    let error = f.session.access_token().await.expect_err("426");
    assert_eq!(error.code(), "app-update-required");
    assert_eq!(stored(&f.vault).as_deref(), Some("rt_1"));
}

#[tokio::test]
async fn a_failed_refresh_falls_back_to_the_unexpired_token() {
    let f = fixture().await;
    // 30 s left: due for a refresh, but still usable.
    mount_login(&f.server, "at_1", 30, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/refresh"))
        .respond_with(ResponseTemplate::new(503).set_body_string("unavailable"))
        .expect(1)
        .mount(&f.server)
        .await;

    f.session.sign_in(&login_request()).await.expect("sign in");
    assert_eq!(f.session.access_token().await.expect("token"), "at_1");
    assert_eq!(stored(&f.vault).as_deref(), Some("rt_1"));
}

#[tokio::test]
async fn sign_out_calls_logout_and_deletes_the_refresh_token() {
    let f = fixture().await;
    mount_login(&f.server, "at_1", 600, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/logout"))
        .and(header("Authorization", "DPoP at_1"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&f.server)
        .await;

    f.session.sign_in(&login_request()).await.expect("sign in");
    f.session.sign_out().await.expect("sign out");

    assert_eq!(stored(&f.vault), None);
    assert!(matches!(
        f.session.access_token().await,
        Err(ApiError::SignedOut)
    ));
}

#[tokio::test]
async fn sign_out_clears_locally_even_when_the_server_call_fails() {
    let f = fixture().await;
    mount_login(&f.server, "at_1", 600, "rt_1").await;
    Mock::given(method("POST"))
        .and(path("/api/v1/candidate-auth/logout"))
        .respond_with(ResponseTemplate::new(503).set_body_string("unavailable"))
        .expect(1)
        .mount(&f.server)
        .await;
    f.session.sign_in(&login_request()).await.expect("sign in");

    let error = f.session.sign_out().await.expect_err("logout failed");
    assert_eq!(error.code(), "http-503");
    assert_eq!(stored(&f.vault), None);
    assert!(matches!(
        f.session.access_token().await,
        Err(ApiError::SignedOut)
    ));
}

#[tokio::test]
async fn signing_out_when_signed_out_is_fine() {
    let f = fixture().await;
    f.session.sign_out().await.expect("nothing to do");
}
