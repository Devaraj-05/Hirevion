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

/// Starts the desktop app. Returns when the last window closes.
pub fn run() {
    // One TLS provider for the updater and crash reporting (ring, as the API client uses).
    let _ = rustls::crypto::ring::default_provider().install_default();
    let _crash_reporting = crash::init(env!("CARGO_PKG_VERSION"));
    let (integrity_variables, debugger_present) = startup_integrity();
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
            #[cfg(windows)]
            {
                let window = app
                    .get_webview_window("main")
                    .ok_or("the main window is missing from tauri.conf.json")?;
                permissions::install(&window, permissions::allowed_origins(app.config()))?;
            }
            let data_dir = app.path().app_local_data_dir()?;
            let version = app.package_info().version.to_string();
            let state =
                app::AppState::new(&version, &data_dir, integrity_variables, debugger_present)?;
            app.manage(state);
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
