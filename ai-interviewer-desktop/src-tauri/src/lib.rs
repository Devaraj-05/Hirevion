//! Hirevion AI Interview desktop app (Tauri 2).

// Spike support (SP-00d) is compiled into debug builds only.
#[cfg(debug_assertions)]
mod perf;
mod permissions;
#[cfg(debug_assertions)]
mod spike;

use tauri::Manager;

/// Starts the desktop app. Returns when the last window closes.
pub fn run() {
    let builder = tauri::Builder::default().setup(|app| {
        #[cfg(windows)]
        {
            let window = app
                .get_webview_window("main")
                .ok_or("the main window is missing from tauri.conf.json")?;
            permissions::install(&window, permissions::allowed_origins(app.config()))?;
        }
        #[cfg(not(windows))]
        let _ = app;
        Ok(())
    });

    // Spike commands exist only in debug builds (SP-00d); release builds expose none.
    #[cfg(debug_assertions)]
    let builder = builder
        .manage(spike::SpikeState::from_env())
        .invoke_handler(tauri::generate_handler![
            spike::spike_config,
            spike::spike_report,
            spike::spike_save_segment
        ]);

    builder
        .run(tauri::generate_context!())
        .expect("the Hirevion desktop app failed to start");
}
