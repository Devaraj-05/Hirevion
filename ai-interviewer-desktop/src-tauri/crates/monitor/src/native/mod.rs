//! The Win32 side: thin scans whose results the pure trackers in [`crate::track`] diff.

pub(crate) mod devices;
pub(crate) mod displays;
pub(crate) mod environment;
pub(crate) mod focus;
pub(crate) mod processes;
pub(crate) mod signature;
pub(crate) mod windows;

use ::windows::Win32::Foundation::{CloseHandle, HANDLE};

/// A kernel handle closed on drop.
pub(crate) struct OwnedHandle(pub(crate) HANDLE);

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        if !self.0.is_invalid() {
            // SAFETY: the handle was returned open by the API that created it and is closed
            // exactly once, here.
            let _ = unsafe { CloseHandle(self.0) };
        }
    }
}

/// A NUL-terminated UTF-16 buffer up to its first NUL, as a `String`.
pub(crate) fn from_wide(buffer: &[u16]) -> String {
    let end = buffer.iter().position(|&c| c == 0).unwrap_or(buffer.len());
    String::from_utf16_lossy(&buffer[..end])
}

/// A `&str` or path as a NUL-terminated UTF-16 buffer.
pub(crate) fn to_wide(text: &std::ffi::OsStr) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    text.encode_wide().chain(std::iter::once(0)).collect()
}

/// This machine's clock, in milliseconds since the Unix epoch.
pub(crate) fn local_now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_millis()).unwrap_or(i64::MAX))
}
