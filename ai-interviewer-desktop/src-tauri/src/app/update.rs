//! The signed updater (SP-08c, ADR-0019).
//!
//! The update-required screen calls [`update_install`]; the webview never talks to the updater
//! plugin itself (no `updater:*` permission is granted), so it never sees a URL or a signature.
//!
//! Three guards stand between the server and a new install:
//!
//! 1. **HTTPS.** Release builds refuse a plain-http manifest (the plugin's own check).
//! 2. **A signature.** The plugin verifies the download against the minisign public key in
//!    `tauri.conf.json`; a bundle signed by any other key is refused.
//! 3. **No downgrade.** [`is_upgrade`] accepts only a strictly newer version, and
//!    `requireSignedVersion` makes the plugin check that the signature was made for the version
//!    the manifest announces, so a genuine older bundle can't be passed off as a newer one.

use hv_api_client::{ApiClient, ApiError, Method, Url};
use hv_security::dpop;
use semver::Version;
use serde::Serialize;
use tauri::ipc::Channel;
use tauri::{AppHandle, Manager, Runtime, State};
use tauri_plugin_updater::{Update, UpdaterExt};

use crate::crash;

use super::error::{CommandError, CommandResult};
use super::state::{AppState, Backend};

/// The updater's name for Windows in `{{target}}` and in the manifest's `platforms` keys.
const TARGET: &str = "windows";

/// The only rule for taking an update: it must be strictly newer than what runs now.
pub fn is_upgrade(current: &Version, offered: &Version) -> bool {
    offered > current
}

/// The updater plugin, with the downgrade guard installed for every updater it hands out.
pub fn plugin<R: Runtime>() -> tauri::plugin::TauriPlugin<R, tauri_plugin_updater::Config> {
    tauri_plugin_updater::Builder::new()
        .default_version_comparator(|current, release| is_upgrade(&current, &release.version))
        .build()
}

/// `desktop/update-manifest/windows/{arch}/{version}?channel=…` under the API root, using the
/// updater's architecture names (`x86_64`, `aarch64`).
pub fn manifest_url(base: &Url, version: &str, channel: &str) -> Result<Url, String> {
    let mut url = base.clone();
    url.path_segments_mut()
        .map_err(|()| "the API root can't carry a path".to_owned())?
        .pop_if_empty()
        .extend([
            "desktop",
            "update-manifest",
            TARGET,
            std::env::consts::ARCH,
            version,
        ]);
    url.query_pairs_mut().append_pair("channel", channel);
    Ok(url)
}

/// What runs just before the installer ends the app. On Windows the updater plugin exits the
/// process itself, so `RunEvent::Exit` never comes: stop the interview services, send what crash
/// reporting has queued, then let the plugin clean up.
pub fn before_exit<R: Runtime>(app: &AppHandle<R>) -> impl Fn() + Send + Sync + 'static {
    let app = app.clone();
    move || {
        run_exit_steps(
            || {
                if let Some(state) = app.try_state::<AppState>() {
                    state.services.stop_for_exit();
                }
            },
            crash::flush,
            || app.cleanup_before_exit(),
        );
    }
}

/// The exit steps, in order: services first (so what stopping them queues is sent), then crash
/// reports, then the plugin's own cleanup.
fn run_exit_steps(stop_services: impl FnOnce(), flush: impl FnOnce(), cleanup: impl FnOnce()) {
    stop_services();
    flush();
    cleanup();
}

/// Asks the manifest endpoint for a newer release. `dpop` (a proof for exactly this request)
/// lets the server place this device in a staged rollout.
pub async fn find_update<R: Runtime>(
    app: &AppHandle<R>,
    endpoint: Url,
    dpop: Option<String>,
) -> Result<Option<Update>, tauri_plugin_updater::Error> {
    let mut builder = app
        .updater_builder()
        .endpoints(vec![endpoint])?
        .on_before_exit(before_exit(app));
    if let Some(proof) = dpop {
        builder = builder.header("DPoP", proof)?;
    }
    builder.build()?.check().await
}

/// The newer release this device may have, or `None`.
///
/// The plugin turns *every* non-success answer into "release not found", which would show a 401,
/// 500 or 503 as "no update". So when it says that, the same request is made once more through
/// the API client, which knows the status: 404 (and 204) mean there is no update, anything else
/// is an error the candidate is told about and can retry.
pub async fn check<R: Runtime>(
    app: &AppHandle<R>,
    api: &ApiClient,
    version: &str,
    channel: &str,
) -> CommandResult<Option<Update>> {
    let endpoint = manifest_url(api.base(), version, channel)
        .map_err(|detail| CommandError::new("update-failed", detail))?;
    let proof = dpop::proof(
        api.signer().as_ref(),
        "GET",
        endpoint.as_str(),
        None,
        None,
        api.server_now_ms().div_euclid(1000),
    )
    .map_err(|error| CommandError::new("security", error.to_string()))?;
    let path = endpoint
        .as_str()
        .strip_prefix(api.base().as_str())
        .map(str::to_owned)
        .ok_or_else(|| {
            CommandError::new(
                "update-failed",
                "the manifest is outside the API".to_owned(),
            )
        })?;
    match find_update(app, endpoint, Some(proof)).await {
        Ok(found) => Ok(found),
        Err(tauri_plugin_updater::Error::ReleaseNotFound) => explain_refusal(api, &path).await,
        Err(error) => Err(command_error(&error)),
    }
}

async fn explain_refusal(api: &ApiClient, path: &str) -> CommandResult<Option<Update>> {
    match api.send_value(Method::GET, path, None, None).await {
        // Nothing to offer (204 reads as null) or no such release: not an error.
        Ok(serde_json::Value::Null) | Err(ApiError::Problem { status: 404, .. }) => Ok(None),
        // The plugin was refused but the same request now works: a hiccup on the server.
        Ok(_) => Err(CommandError::new(
            "update-server-error",
            "the update service answered inconsistently".to_owned(),
        )),
        Err(ApiError::Problem { status, code, .. }) => Err(CommandError::new(
            "update-server-error",
            format!("HTTP {status} {code}"),
        )),
        Err(other) => Err(other.into()),
    }
}

fn command_error(error: &tauri_plugin_updater::Error) -> CommandError {
    use tauri_plugin_updater::Error as E;
    let code = match error {
        E::Minisign(_)
        | E::Base64(_)
        | E::SignatureUtf8(_)
        | E::SignedVersionMismatch { .. }
        | E::MissingSignedVersion => "update-signature-invalid",
        E::Reqwest(_) | E::Network(_) => "network",
        E::ReleaseNotFound | E::TargetNotFound(_) | E::TargetsNotFound(_) => "update-unavailable",
        _ => "update-failed",
    };
    CommandError::new(code, error.to_string())
}

/// What the update screen shows while a download runs.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum UpdateProgress {
    Downloading {
        downloaded: u64,
        total: Option<u64>,
    },
    /// Sent only once the download has been verified against the signing key.
    Installing,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct UpdateOutcome {
    /// `up-to-date` (nothing newer for this device) or `installed`. On Windows an install
    /// ends the app and the installer starts the new version, so the webview sees only the
    /// first.
    pub status: &'static str,
    pub version: Option<String>,
}

/// Check → download (with progress) → verify → install → relaunch. The NSIS installer runs
/// per user (no admin prompt) and starts the new version itself (`/R`) when it finishes.
#[tauri::command]
pub async fn update_install(
    app: AppHandle,
    state: State<'_, AppState>,
    on_progress: Channel<UpdateProgress>,
) -> CommandResult<UpdateOutcome> {
    let up_to_date = UpdateOutcome {
        status: "up-to-date",
        version: None,
    };
    let Backend::Live(session) = &state.backend else {
        return Ok(up_to_date);
    };
    let api = session.api();
    // Proofs carry server time.
    api.sync_clock().await?;
    let Some(mut update) = check(&app, api, &state.info.version, &state.info.channel).await? else {
        return Ok(up_to_date);
    };
    // The proof was for the manifest; the bundle's host doesn't need it.
    update.headers.clear();
    let version = update.version.clone();

    let mut downloaded = 0_u64;
    let progress = on_progress.clone();
    // `download` returns only after the signature has been verified (`on_download_finish`
    // fires before that, so it is not used to claim "installing").
    let bytes = update
        .download(
            move |chunk, total| {
                downloaded += chunk as u64;
                let _ = progress.send(UpdateProgress::Downloading { downloaded, total });
            },
            || {},
        )
        .await
        .map_err(|error| command_error(&error))?;
    let _ = on_progress.send(UpdateProgress::Installing);
    // On Windows `install` runs the installer and exits the process after the before-exit
    // hook (`before_exit`); it blocks, so it runs off the async workers.
    tauri::async_runtime::spawn_blocking(move || update.install(bytes))
        .await
        .map_err(|error| CommandError::new("update-failed", error.to_string()))?
        .map_err(|error| command_error(&error))?;
    Ok(UpdateOutcome {
        status: "installed",
        version: Some(version),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine as _;
    use serde_json::json;

    fn version(text: &str) -> Version {
        Version::parse(text).expect("a version")
    }

    #[test]
    fn only_a_strictly_newer_version_is_an_upgrade() {
        assert!(is_upgrade(&version("0.1.0"), &version("0.1.1")));
        assert!(is_upgrade(&version("0.1.0"), &version("1.0.0")));
        assert!(is_upgrade(&version("1.0.0-beta.1"), &version("1.0.0")));
        assert!(!is_upgrade(&version("0.1.1"), &version("0.1.0")));
        assert!(!is_upgrade(&version("0.1.0"), &version("0.1.0")));
        assert!(!is_upgrade(&version("1.0.0"), &version("1.0.0-beta.1")));
        assert!(!is_upgrade(&version("2.0.0"), &version("1.99.99")));
    }

    #[test]
    fn the_manifest_url_names_this_device_and_channel() {
        let base = Url::parse("https://api.example.test/api/v1/").expect("a URL");
        let url = manifest_url(&base, "0.1.0", "stable").expect("a URL");
        assert_eq!(
            url.as_str(),
            format!(
                "https://api.example.test/api/v1/desktop/update-manifest/windows/{}/0.1.0?channel=stable",
                std::env::consts::ARCH
            )
        );
    }

    #[test]
    fn the_app_version_is_the_same_in_cargo_and_tauri_conf() {
        // The updater compares the version in tauri.conf.json; the crash reports use Cargo's.
        let conf: serde_json::Value =
            serde_json::from_str(include_str!("../../tauri.conf.json")).expect("tauri.conf.json");
        assert_eq!(conf["version"], env!("CARGO_PKG_VERSION"));
    }

    #[test]
    fn the_config_pins_a_signing_key_a_signed_version_and_https() {
        let conf: serde_json::Value =
            serde_json::from_str(include_str!("../../tauri.conf.json")).expect("tauri.conf.json");
        let updater = &conf["plugins"]["updater"];
        let key = updater["pubkey"].as_str().expect("a pubkey");
        // A minisign public key file, base64-encoded: "untrusted comment: minisign public key …".
        let decoded = String::from_utf8(
            base64::engine::general_purpose::STANDARD
                .decode(key)
                .expect("the pubkey is base64"),
        )
        .expect("the pubkey is text");
        assert!(decoded.starts_with("untrusted comment: minisign public key"));
        assert_eq!(updater["requireSignedVersion"], true);
        assert!(updater.get("dangerousInsecureTransportProtocol").is_none());
        assert!(updater.get("allowDowngrades").is_none());
        for endpoint in updater["endpoints"].as_array().expect("endpoints") {
            assert!(endpoint.as_str().expect("a URL").starts_with("https://"));
        }
    }

    #[test]
    fn the_exit_steps_run_services_then_crash_reports_then_cleanup() {
        let order = std::cell::RefCell::new(Vec::new());
        run_exit_steps(
            || order.borrow_mut().push("services"),
            || order.borrow_mut().push("flush"),
            || order.borrow_mut().push("cleanup"),
        );
        assert_eq!(*order.borrow(), ["services", "flush", "cleanup"]);
    }

    #[test]
    fn progress_serialises_with_an_event_tag() {
        let value = serde_json::to_value(UpdateProgress::Downloading {
            downloaded: 10,
            total: Some(20),
        })
        .expect("json");
        assert_eq!(
            value,
            json!({ "event": "downloading", "downloaded": 10, "total": 20 })
        );
        assert_eq!(
            serde_json::to_value(UpdateProgress::Installing).expect("json"),
            json!({ "event": "installing" })
        );
    }
}
