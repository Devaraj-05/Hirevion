//! Hirevion AI Interview desktop app (Tauri 2).

/// Starts the desktop app. Returns when the last window closes.
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("the Hirevion desktop app failed to start");
}
