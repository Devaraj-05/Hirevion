//! The Windows measurements behind each check. Thresholds stay in [`crate::classify`].

mod com;
mod media_foundation;
mod privacy;
mod registry;
pub(crate) mod screen_capture;
mod system;

use crate::classify::{MediaFoundationProbe, classify_media_foundation};
use crate::result::CheckResult;

/// The Windows version and build (the `os` check on its own).
pub(crate) fn os() -> CheckResult {
    system::os()
}

/// Every native check, in [`crate::NATIVE_CHECKS`] order. Media Foundation runs on its own
/// COM thread while the CPU is sampled, so the whole set takes about half a second.
pub(crate) fn checks() -> Vec<CheckResult> {
    std::thread::scope(|scope| {
        let media = scope.spawn(media_foundation::check);
        let cpu = system::cpu();
        let memory = system::memory();
        let disk = system::disk();
        let displays = system::displays();
        let privacy = privacy::check();
        let os = system::os();
        let media = media.join().unwrap_or_else(|_| {
            classify_media_foundation(&MediaFoundationProbe::Failed(
                "the check stopped unexpectedly".to_owned(),
            ))
        });
        vec![cpu, memory, disk, displays, privacy, media, os]
    })
}

/// A Windows error as text, falling back to its HRESULT when Windows has no message for it.
fn describe(error: &windows::core::Error) -> String {
    let message = error.message();
    let message = message.trim();
    if message.is_empty() {
        format!("error {:#010x}", error.code().0)
    } else {
        message.to_owned()
    }
}

/// A NUL-terminated UTF-16 copy of `text` for Windows APIs.
fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}
