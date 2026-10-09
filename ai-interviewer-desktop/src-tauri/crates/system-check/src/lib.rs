//! Native system checks for the Hirevion desktop app (PRD §29).
//!
//! The thresholds live in [`classify`] as pure functions; the Windows code only measures.
//! The webview runs the checks that need its media stack (camera, microphone, speaker).
//! Off Windows every check is `skipped`, so the crate still builds and tests on Linux.

pub mod classify;
#[cfg(windows)]
mod native;
mod result;

pub use result::{CheckResult, NATIVE_CHECKS, Status, names};

#[cfg(not(windows))]
const NOT_WINDOWS: &str = "This check runs only on Windows.";

/// CPU, memory, disk, displays, privacy settings, Media Foundation and the OS build, in
/// [`NATIVE_CHECKS`] order. Every result carries a `value`; anything short of a pass also
/// carries a `detail`.
///
/// Blocks for about half a second (the CPU sample): call it off the UI thread.
#[must_use]
pub fn native_checks() -> Vec<CheckResult> {
    #[cfg(windows)]
    {
        native::checks()
    }
    #[cfg(not(windows))]
    {
        NATIVE_CHECKS
            .iter()
            .map(|check| CheckResult::skipped(check, NOT_WINDOWS))
            .collect()
    }
}

/// Captures one frame from every display (`screen_capture`), passing when each delivers
/// one within two seconds. Runs on its own COM thread, so the caller's apartment doesn't
/// matter.
///
/// Blocks for up to about five seconds: call it off the UI thread.
#[must_use]
pub fn screen_capture_probe() -> CheckResult {
    #[cfg(windows)]
    {
        native::screen_capture::probe()
    }
    #[cfg(not(windows))]
    {
        CheckResult::skipped(names::SCREEN_CAPTURE, NOT_WINDOWS)
    }
}
