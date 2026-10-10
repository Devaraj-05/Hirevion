//! SP-11 exit criterion: no keystroke content is ever read, so no code that could read it may
//! exist. This scans the crate's sources for every Windows API that observes keys.

use std::path::Path;

/// APIs and messages that observe keyboard input.
const FORBIDDEN: &[&str] = &[
    "SetWindowsHookEx",
    "WH_KEYBOARD",
    "WH_KEYBOARD_LL",
    "KBDLLHOOKSTRUCT",
    "GetAsyncKeyState",
    "GetKeyState",
    "GetKeyboardState",
    "RegisterRawInputDevices",
    "GetRawInputData",
    "RegisterHotKey",
    "WM_KEYDOWN",
    "WM_SYSKEYDOWN",
    "WM_CHAR",
    "WM_INPUT",
    "ToUnicode",
    "ToAscii",
    "MapVirtualKey",
    "Win32_UI_Input_KeyboardAndMouse",
    "KeyboardAndMouse",
];

fn rust_and_manifest_files(dir: &Path, out: &mut Vec<std::path::PathBuf>) {
    for entry in std::fs::read_dir(dir).expect("read dir") {
        let path = entry.expect("entry").path();
        if path.is_dir() {
            rust_and_manifest_files(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs" || e == "toml") {
            out.push(path);
        }
    }
}

#[test]
fn the_crate_contains_no_keyboard_observation_code() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut files = vec![root.join("Cargo.toml")];
    rust_and_manifest_files(&root.join("src"), &mut files);
    assert!(files.len() > 2, "the scan found the sources");
    let mut found = Vec::new();
    for file in &files {
        let text = std::fs::read_to_string(file).expect("read source");
        for needle in FORBIDDEN {
            if text.contains(needle) {
                found.push(format!("{} uses {needle}", file.display()));
            }
        }
    }
    assert!(
        found.is_empty(),
        "keyboard observation code found: {found:#?}"
    );
}
