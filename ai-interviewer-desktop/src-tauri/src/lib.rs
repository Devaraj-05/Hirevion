//! Hirevion AI Interview desktop app (Tauri 2).

mod app;
mod crash;

// The updater is public so its integration test (tests/updater.rs) can drive it.
pub use app::update;
// Spike support (SP-00d) is compiled into debug builds only.
#[cfg(debug_assertions)]
mod perf;
mod permissions;
#[cfg(debug_assertions)]
mod spike;

use tauri::Manager;

/// Integrity first (ADR-0018): before WebView2 can read them, release builds remove the
/// `WEBVIEW2_*` variables that redirect the browser or add switches. Debug builds keep them
/// (the spike runs use fake media devices that way) but still report them.
fn startup_integrity() -> (Vec<String>, bool) {
    let found = if cfg!(debug_assertions) {
        hv_security::integrity::WEBVIEW_ENVIRONMENT_VARIABLES
            .iter()
            .filter(|name| std::env::var_os(name).is_some())
            .map(|name| (*name).to_owned())
            .collect()
    } else {
        hv_security::integrity::sanitize_webview_environment()
    };
    (found, hv_security::integrity::debugger_present())
}

/// The main window, built from `tauri.conf.json` (which sets `create: false` for it).
fn main_window(app: &tauri::App) -> tauri::Result<tauri::WebviewWindow> {
    let config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .ok_or_else(|| tauri::Error::WindowNotFound)?;
    let builder = tauri::WebviewWindowBuilder::from_config(app, config)?;
    #[cfg(all(windows, debug_assertions))]
    let builder = with_driver_environment(builder);
    builder.build()
}

/// Debug builds only: hands the WebView2 browser switches and user-data folder that a WebDriver
/// (msedgedriver, under tauri-driver) passes as environment variables to WebView2 through its
/// API instead. On GitHub's Windows runners the runtime does not apply those environment
/// overrides (the browser started without `--remote-debugging-port`, so no session could be
/// created), while options given through the API are always applied. Release builds never do
/// this: they remove those variables at start (ADR-0018).
#[cfg(all(windows, debug_assertions))]
fn with_driver_environment<R: tauri::Runtime, M: Manager<R>>(
    mut builder: tauri::WebviewWindowBuilder<'_, R, M>,
) -> tauri::WebviewWindowBuilder<'_, R, M> {
    // wry's own defaults, which giving any argument would otherwise replace.
    const WRY_DEFAULTS: &str = "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required";
    if let Ok(extra) = std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") {
        builder = builder.additional_browser_args(&format!("{WRY_DEFAULTS} {extra}"));
    }
    if let Some(folder) = std::env::var_os("WEBVIEW2_USER_DATA_FOLDER") {
        builder = builder.data_directory(std::path::PathBuf::from(folder));
    }
    builder
}

/// Starts the desktop app. Returns when the last window closes.
pub fn run() {
    // One TLS provider for the updater and crash reporting (ring, as the API client uses).
    let _ = rustls::crypto::ring::default_provider().install_default();
    let _crash_reporting = crash::init(env!("CARGO_PKG_VERSION"));
    let (integrity_variables, debugger_present) = startup_integrity();
    // Debug builds say what they inherited (the end-to-end diagnostics read this).
    #[cfg(debug_assertions)]
    eprintln!(
        "hirevion-desktop: debug build; WEBVIEW2 variables: {integrity_variables:?}; WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS={:?}",
        std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").ok()
    );
    let builder = tauri::Builder::default()
        // A second launch focuses the running app instead of starting another session.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        // Signed updates (SP-08c); driven only by the update_install command.
        .plugin(app::update::plugin())
        .setup(move |app| {
            let data_dir = app.path().app_local_data_dir()?;
            let version = app.package_info().version.to_string();
            let state =
                app::AppState::new(&version, &data_dir, integrity_variables, debugger_present)?;
            app.manage(state);
            // The window is made here, after the state its commands read exists.
            #[cfg_attr(not(windows), allow(unused_variables))]
            let window = main_window(app)?;
            #[cfg(windows)]
            permissions::install(&window, permissions::allowed_origins(app.config()))?;
            Ok(())
        });

    // Spike commands exist only in debug builds (SP-00d); release builds expose none of them.
    #[cfg(debug_assertions)]
    let builder = builder
        .manage(spike::SpikeState::from_env())
        .invoke_handler(tauri::generate_handler![
            app::commands::app_info,
            app::commands::release_check,
            app::commands::sign_in,
            app::commands::verify_code,
            app::commands::resend_code,
            app::commands::sign_out,
            app::commands::profile,
            app::commands::native_checks,
            app::commands::screen_capture_probe,
            app::commands::api_round_trip,
            app::update::update_install,
            crash::crash_report,
            app::interview::interview_request,
            app::service_commands::services_start,
            app::service_commands::services_stop,
            app::service_commands::proctoring_set_devices,
            app::service_commands::proctoring_enqueue,
            app::service_commands::recording_clock,
            app::service_commands::recording_store_segment,
            app::service_commands::upload_progress,
            spike::spike_config,
            spike::spike_report,
            spike::spike_save_segment
        ]);
    #[cfg(not(debug_assertions))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        app::commands::app_info,
        app::commands::release_check,
        app::commands::sign_in,
        app::commands::verify_code,
        app::commands::resend_code,
        app::commands::sign_out,
        app::commands::profile,
        app::commands::native_checks,
        app::commands::screen_capture_probe,
        app::commands::api_round_trip,
        app::update::update_install,
        crash::crash_report,
        app::interview::interview_request,
        app::service_commands::services_start,
        app::service_commands::services_stop,
        app::service_commands::proctoring_set_devices,
        app::service_commands::proctoring_enqueue,
        app::service_commands::recording_clock,
        app::service_commands::recording_store_segment,
        app::service_commands::upload_progress
    ]);

    builder
        .build(tauri::generate_context!())
        .expect("the Hirevion desktop app failed to start")
        .run(|app, event| {
            // Closing the app mid-interview: stop the monitor and the screen recorder cleanly.
            // Whatever hasn't reached the server stays encrypted on disk and uploads at the
            // next launch.
            if matches!(event, tauri::RunEvent::Exit) {
                if let Some(state) = app.try_state::<app::AppState>() {
                    state.services.stop_for_exit();
                }
                crash::flush();
            }
        });
}
