//! Hirevion AI Interview desktop app (Tauri 2).

mod app;
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
    let (integrity_variables, debugger_present) = startup_integrity();
    let builder = tauri::Builder::default()
        // A second launch focuses the running app instead of starting another session.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
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
            app::commands::submit_checks,
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
        app::commands::submit_checks
    ]);

    builder
        .run(tauri::generate_context!())
        .expect("the Hirevion desktop app failed to start");
}
