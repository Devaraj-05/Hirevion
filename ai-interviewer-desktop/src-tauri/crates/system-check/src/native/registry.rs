//! Small typed reads from the registry.

use super::wide;
use windows::Win32::Foundation::ERROR_SUCCESS;
use windows::Win32::System::Registry::{
    HKEY, REG_ROUTINE_FLAGS, RRF_RT_REG_DWORD, RRF_RT_REG_SZ, RegGetValueW,
};
use windows::core::PCWSTR;

/// A `REG_SZ` value, or `None` when the key or value is missing or isn't a short string.
pub(super) fn read_string(root: HKEY, subkey: &str, value: &str) -> Option<String> {
    let mut buffer = [0u16; 256];
    let capacity = size_of_val(&buffer);
    let size = read(
        root,
        subkey,
        value,
        RRF_RT_REG_SZ,
        buffer.as_mut_ptr().cast(),
        capacity,
    )?;
    let chars = (size / 2).min(buffer.len());
    let text = &buffer[..chars];
    let end = text.iter().position(|&c| c == 0).unwrap_or(text.len());
    Some(String::from_utf16_lossy(&text[..end]))
}

/// A `REG_DWORD` value, or `None` when it is missing.
pub(super) fn read_dword(root: HKEY, subkey: &str, value: &str) -> Option<u32> {
    let mut data = 0u32;
    read(
        root,
        subkey,
        value,
        RRF_RT_REG_DWORD,
        (&raw mut data).cast(),
        size_of::<u32>(),
    )?;
    Some(data)
}

/// Reads one value into `data` (`capacity` bytes) and returns the bytes written.
fn read(
    root: HKEY,
    subkey: &str,
    value: &str,
    kind: REG_ROUTINE_FLAGS,
    data: *mut core::ffi::c_void,
    capacity: usize,
) -> Option<usize> {
    let subkey = wide(subkey);
    let value = wide(value);
    let mut size = u32::try_from(capacity).ok()?;
    // SAFETY: both names are NUL-terminated and outlive the call; `data` points to
    // `capacity` writable bytes owned by the caller, and `size` says so.
    let status = unsafe {
        RegGetValueW(
            root,
            PCWSTR(subkey.as_ptr()),
            PCWSTR(value.as_ptr()),
            kind,
            None,
            Some(data),
            Some(&raw mut size),
        )
    };
    if status != ERROR_SUCCESS {
        return None;
    }
    usize::try_from(size).ok()
}
