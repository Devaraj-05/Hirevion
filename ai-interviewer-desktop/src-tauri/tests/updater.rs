//! The updater against a fake manifest server: a downgrade the server offers is refused, a newer
//! version is taken. The app is a Tauri mock app configured with the `plugins.updater` section of
//! the real `tauri.conf.json`, so the real downgrade guard and signing settings are the ones
//! under test. (Signature checking itself is the updater plugin's, on download.)

use std::sync::Arc;

use hirevion_desktop_lib::update::{before_exit, check, find_update, plugin};
use hv_api_client::ApiClient;
use hv_security::SoftwareKey;
use semver::Version;
use serde_json::json;
use tauri::test::{MockRuntime, mock_builder, mock_context, noop_assets};
use url::Url;
use wiremock::matchers::{header_exists, method, path, path_regex};
use wiremock::{Mock, MockServer, ResponseTemplate};

/// An app that runs `running`, with the updater configured as in `tauri.conf.json`.
fn app(running: &str) -> tauri::App<MockRuntime> {
    let conf: serde_json::Value =
        serde_json::from_str(include_str!("../tauri.conf.json")).expect("tauri.conf.json");
    let mut updater = conf["plugins"]["updater"].clone();
    updater["endpoints"] = json!([]);
    let mut context = mock_context(noop_assets());
    context.package_info_mut().version = Version::parse(running).expect("a version");
    context
        .config_mut()
        .plugins
        .0
        .insert("updater".into(), updater);
    mock_builder()
        .plugin(plugin())
        .build(context)
        .expect("a mock app")
}

/// Serves a manifest announcing `offered`, and only to requests that carry a DPoP proof.
async fn manifest(server: &MockServer, offered: &str) -> Url {
    let platform =
        json!({ "signature": "c2ln", "url": "https://downloads.example.test/setup.exe" });
    Mock::given(method("GET"))
        .and(path("/manifest"))
        .and(header_exists("dpop"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "version": offered,
            "notes": "",
            "pub_date": "2026-10-14T00:00:00Z",
            "platforms": {
                "windows-x86_64": platform,
                "windows-aarch64": platform,
                "linux-x86_64": platform,
            },
        })))
        .mount(server)
        .await;
    Url::parse(&format!("{}/manifest", server.uri())).expect("a URL")
}

#[tokio::test]
async fn refuses_a_downgrade_the_server_offers() {
    let server = MockServer::start().await;
    let endpoint = manifest(&server, "0.0.9").await;
    let app = app("0.1.0");
    let found = find_update(app.handle(), endpoint, Some("proof".into()))
        .await
        .expect("a check");
    assert!(found.is_none(), "an older version must not be offered");
}

#[tokio::test]
async fn refuses_the_version_it_already_runs() {
    let server = MockServer::start().await;
    let endpoint = manifest(&server, "0.1.0").await;
    let app = app("0.1.0");
    let found = find_update(app.handle(), endpoint, Some("proof".into()))
        .await
        .expect("a check");
    assert!(found.is_none());
}

#[tokio::test]
async fn offers_a_newer_version() {
    let server = MockServer::start().await;
    let endpoint = manifest(&server, "0.2.0").await;
    let app = app("0.1.0");
    let found = find_update(app.handle(), endpoint, Some("proof".into()))
        .await
        .expect("a check");
    assert_eq!(found.expect("an update").version, "0.2.0");
}

#[tokio::test]
async fn no_content_means_up_to_date() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(204))
        .mount(&server)
        .await;
    let endpoint = Url::parse(&format!("{}/manifest", server.uri())).expect("a URL");
    let app = app("0.1.0");
    assert!(
        find_update(app.handle(), endpoint, None)
            .await
            .expect("a check")
            .is_none()
    );
}

// What the candidate is told when the manifest endpoint itself is the problem. The plugin turns
// every non-2xx answer into "release not found", so `check` asks the API client what the status was.

const MANIFEST_PATH: &str = "/api/v1/desktop/update-manifest/windows/.*/0.1.0";

fn api(server: &MockServer) -> ApiClient {
    let base = Url::parse(&format!("{}/api/v1/", server.uri())).expect("a URL");
    ApiClient::new(base, Arc::new(SoftwareKey::generate()), "test/0.1.0".into()).expect("a client")
}

async fn answer(server: &MockServer, template: ResponseTemplate) {
    Mock::given(method("GET"))
        .and(path_regex(MANIFEST_PATH))
        .respond_with(template)
        .mount(server)
        .await;
}

#[tokio::test]
async fn a_server_error_is_reported_not_hidden_as_no_update() {
    for status in [500, 502, 503, 429] {
        let server = MockServer::start().await;
        answer(&server, ResponseTemplate::new(status)).await;
        let app = app("0.1.0");
        let error = check(app.handle(), &api(&server), "0.1.0", "stable")
            .await
            .map(|found| found.map(|update| update.version))
            .expect_err(&format!("HTTP {status} is an error"));
        assert_eq!(error.code, "update-server-error", "HTTP {status}");
        assert!(
            error
                .detail
                .as_deref()
                .is_some_and(|d| d.contains(&status.to_string()))
        );
    }
}

#[tokio::test]
async fn a_refused_proof_is_reported_too() {
    let server = MockServer::start().await;
    answer(
        &server,
        ResponseTemplate::new(401).set_body_json(json!({ "code": "dpop-invalid" })),
    )
    .await;
    let app = app("0.1.0");
    let error = check(app.handle(), &api(&server), "0.1.0", "stable")
        .await
        .map(|found| found.map(|update| update.version))
        .expect_err("HTTP 401 is an error");
    assert_eq!(error.code, "update-server-error");
    assert!(
        error
            .detail
            .as_deref()
            .is_some_and(|d| d.contains("dpop-invalid"))
    );
}

#[tokio::test]
async fn not_found_and_no_content_mean_no_update() {
    for status in [404, 204] {
        let server = MockServer::start().await;
        answer(&server, ResponseTemplate::new(status)).await;
        let app = app("0.1.0");
        let found = check(app.handle(), &api(&server), "0.1.0", "stable")
            .await
            .map(|found| found.map(|update| update.version))
            .expect("not an error");
        assert_eq!(found, None, "HTTP {status}");
    }
}

#[tokio::test]
async fn an_unreachable_server_is_a_network_error() {
    // A port nothing listens on (a dropped MockServer goes back to a pool and keeps answering).
    let port = std::net::TcpListener::bind("127.0.0.1:0")
        .expect("a free port")
        .local_addr()
        .expect("an address")
        .port();
    let base = Url::parse(&format!("http://127.0.0.1:{port}/api/v1/")).expect("a URL");
    let api = ApiClient::new(base, Arc::new(SoftwareKey::generate()), "test/0.1.0".into())
        .expect("a client");
    let app = app("0.1.0");
    let error = check(app.handle(), &api, "0.1.0", "stable")
        .await
        .map(|found| found.map(|update| update.version))
        .expect_err("nothing is listening");
    assert_eq!(error.code, "network");
}

#[tokio::test]
async fn checking_takes_a_newer_version_and_refuses_an_older_one() {
    for (offered, expected) in [("0.2.0", Some("0.2.0".to_owned())), ("0.0.9", None)] {
        let server = MockServer::start().await;
        let platform =
            json!({ "signature": "c2ln", "url": "https://downloads.example.test/setup.exe" });
        answer(
            &server,
            ResponseTemplate::new(200).set_body_json(json!({
                "version": offered,
                "notes": "",
                "pub_date": "2026-10-14T00:00:00Z",
                "platforms": { "windows-x86_64": platform, "windows-aarch64": platform },
            })),
        )
        .await;
        let app = app("0.1.0");
        let found = check(app.handle(), &api(&server), "0.1.0", "stable")
            .await
            .map(|found| found.map(|update| update.version))
            .expect("a check");
        assert_eq!(found, expected, "offered {offered}");
    }
}

#[tokio::test]
async fn the_before_exit_hook_runs_on_an_async_worker() {
    // The plugin calls it from the task that installs the update; stopping services blocks on a
    // runtime, which must not panic there. (No services are managed in the mock app.)
    let app = app("0.1.0");
    let hook = before_exit(app.handle());
    hook();
}
