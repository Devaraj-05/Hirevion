//! Client integrity: WebView2 environment overrides and debuggers.
//!
//! Both findings are reported as `CLIENT_INTEGRITY_WARNING` (SP-11).

/// The WebView2 environment variables that change which browser runs or how: extra command-line
/// arguments (remote debugging, disabled security), another browser folder, another profile
/// folder, another release channel, and script-debugger hooks.
pub const WEBVIEW_ENVIRONMENT_VARIABLES: &[&str] = &[
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
    "WEBVIEW2_USER_DATA_FOLDER",
    "WEBVIEW2_RELEASE_CHANNEL_PREFERENCE",
    "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER",
    "WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER",
];

/// Removes [`WEBVIEW_ENVIRONMENT_VARIABLES`] from this process's environment and returns the
/// names of those that were set.
///
/// Call it first thing in `main`, before WebView2 starts and before any other thread exists.
pub fn sanitize_webview_environment() -> Vec<String> {
    let mut removed = Vec::new();
    for name in WEBVIEW_ENVIRONMENT_VARIABLES {
        if std::env::var_os(name).is_some() {
            // SAFETY: `remove_var` is unsafe because another thread might read the environment
            // at the same time. On Windows the OS serialises environment access (the PEB lock in
            // SetEnvironmentVariableW), and the documented contract of this function is to run at
            // start-up before other threads are spawned, which covers other platforms too.
            unsafe { std::env::remove_var(name) };
            removed.push((*name).to_owned());
        }
    }
    removed
}

/// Whether a debugger is attached to this process (locally or remotely).
#[cfg(windows)]
pub fn debugger_present() -> bool {
    use windows::Win32::System::Diagnostics::Debug::{
        CheckRemoteDebuggerPresent, IsDebuggerPresent,
    };
    use windows::Win32::System::Threading::GetCurrentProcess;
    use windows_core::BOOL;

    // SAFETY: IsDebuggerPresent takes no arguments and only reads this process's PEB.
    let local = unsafe { IsDebuggerPresent() }.as_bool();
    let mut remote = BOOL(0);
    // SAFETY: GetCurrentProcess returns a pseudo-handle that is always valid in this process,
    // and `remote` is a live, writable BOOL for the duration of the call.
    let checked = unsafe { CheckRemoteDebuggerPresent(GetCurrentProcess(), &mut remote) }.is_ok();
    local || (checked && remote.as_bool())
}

/// Whether a debugger is attached to this process. Always `false` off Windows.
#[cfg(not(windows))]
pub fn debugger_present() -> bool {
    false
}
