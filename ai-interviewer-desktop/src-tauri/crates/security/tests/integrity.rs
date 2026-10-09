//! Integrity checks. This file is its own test binary (its own process), so
//! changing the environment here can't disturb the other tests.

use hv_security::integrity;

#[test]
fn sanitize_removes_the_webview_variables_that_were_set() {
    // SAFETY: this test binary has a single test, so no other thread reads or
    // writes the environment while it runs.
    unsafe {
        std::env::set_var(
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            "--remote-debugging-port=9222",
        );
        std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", "C:\\evil");
        std::env::remove_var("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER");
        std::env::remove_var("WEBVIEW2_RELEASE_CHANNEL_PREFERENCE");
        std::env::remove_var("WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER");
        std::env::set_var("HV_UNRELATED", "kept");
    }

    let mut removed = integrity::sanitize_webview_environment();
    removed.sort();
    assert_eq!(
        removed,
        vec![
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS".to_string(),
            "WEBVIEW2_USER_DATA_FOLDER".to_string(),
        ]
    );
    for name in integrity::WEBVIEW_ENVIRONMENT_VARIABLES {
        assert!(std::env::var_os(name).is_none(), "{name} is still set");
    }
    assert_eq!(std::env::var("HV_UNRELATED").as_deref(), Ok("kept"));

    // Nothing left to remove the second time.
    assert!(integrity::sanitize_webview_environment().is_empty());

    // The listed variables are all covered.
    for name in [
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
        "WEBVIEW2_USER_DATA_FOLDER",
        "WEBVIEW2_RELEASE_CHANNEL_PREFERENCE",
        "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER",
    ] {
        assert!(integrity::WEBVIEW_ENVIRONMENT_VARIABLES.contains(&name));
    }

    // Tests don't run under a debugger.
    assert!(!integrity::debugger_present());
}
