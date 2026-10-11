//! The updater against a fake manifest server: a downgrade the server offers is refused, a newer
//! version is taken. The app is a Tauri mock app configured with the `plugins.updater` section of
//! the real `tauri.conf.json`, so the real downgrade guard and signing settings are the ones
//! under test. (Signature checking itself is the updater plugin's, on download.)

use hirevion_desktop_lib::update::{find_update, plugin};
use semver::Version;
use serde_json::json;
use tauri::test::{MockRuntime, mock_builder, mock_context, noop_assets};
use url::Url;
use wiremock::matchers::{header_exists, method, path};
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
