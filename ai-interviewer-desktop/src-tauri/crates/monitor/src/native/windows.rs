//! Top-level windows: titles per process, display affinity and overlay styles.
//!
//! Titles are read with `InternalGetWindowText`, which doesn't send `WM_GETTEXT`, so a hung
//! application can never stall the monitor.

use std::collections::HashMap;
use std::ffi::c_void;

use windows::Win32::Foundation::{HWND, LPARAM, RECT};
use windows::Win32::Graphics::Dwm::{DWMWA_CLOAKED, DwmGetWindowAttribute};
use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GWL_EXSTYLE, GetWindowDisplayAffinity, GetWindowLongPtrW, GetWindowRect,
    GetWindowThreadProcessId, InternalGetWindowText, IsWindowVisible, WS_EX_LAYERED, WS_EX_TOPMOST,
};
use windows_core::BOOL;

use super::from_wide;
use crate::track::WindowFacts;

/// Every top-level window, in z-order.
pub(crate) fn top_level() -> Vec<HWND> {
    unsafe extern "system" fn collect(hwnd: HWND, data: LPARAM) -> BOOL {
        // SAFETY: `data` is the address of the Vec in `top_level`, which outlives the
        // enumeration, and nothing else touches it meanwhile.
        let windows = unsafe { &mut *(data.0 as *mut Vec<HWND>) };
        windows.push(hwnd);
        BOOL::from(true)
    }
    let mut windows: Vec<HWND> = Vec::with_capacity(256);
    // SAFETY: the callback only pushes into `windows`, which lives until the call returns.
    let _ = unsafe { EnumWindows(Some(collect), LPARAM(&raw mut windows as isize)) };
    windows
}

/// The process that owns a window.
pub(crate) fn owner_pid(hwnd: HWND) -> u32 {
    let mut pid = 0u32;
    // SAFETY: `pid` is a live out-parameter; a stale HWND just yields 0.
    unsafe { GetWindowThreadProcessId(hwnd, Some(&raw mut pid)) };
    pid
}

/// A window's title, without sending it a message.
pub(crate) fn title(hwnd: HWND) -> String {
    let mut buffer = [0u16; 512];
    // SAFETY: `buffer` is a live, writable slice; the API writes at most its length.
    let length = unsafe { InternalGetWindowText(hwnd, &mut buffer) };
    from_wide(&buffer[..usize::try_from(length).unwrap_or(0).min(buffer.len())])
}

fn visible(hwnd: HWND) -> bool {
    // SAFETY: reads a window flag; a stale HWND yields false.
    unsafe { IsWindowVisible(hwnd) }.as_bool()
}

/// The non-empty titles of each process's visible top-level windows.
pub(crate) fn titles_by_pid() -> HashMap<u32, Vec<String>> {
    let mut titles: HashMap<u32, Vec<String>> = HashMap::new();
    for hwnd in top_level() {
        if !visible(hwnd) {
            continue;
        }
        let text = title(hwnd);
        if !text.is_empty() {
            titles.entry(owner_pid(hwnd)).or_default().push(text);
        }
    }
    for list in titles.values_mut() {
        list.sort();
        list.dedup();
    }
    titles
}

/// What the window tracker needs about each visible top-level window. `names` maps PIDs to
/// executable names.
pub(crate) fn scan(names: &HashMap<u32, String>) -> Vec<WindowFacts> {
    top_level()
        .into_iter()
        .filter(|hwnd| visible(*hwnd))
        .map(|hwnd| {
            let pid = owner_pid(hwnd);
            let mut affinity = 0u32;
            // SAFETY: `affinity` is a live out-parameter; failure leaves it 0.
            let _ = unsafe { GetWindowDisplayAffinity(hwnd, &raw mut affinity) };
            // SAFETY: reads a window long; a stale HWND yields 0.
            let ex_style = unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) } as u32;
            let mut rect = RECT::default();
            // SAFETY: `rect` is a live out-parameter.
            let _ = unsafe { GetWindowRect(hwnd, &raw mut rect) };
            let mut cloaked = 0u32;
            // SAFETY: DWMWA_CLOAKED writes a DWORD into `cloaked`, whose size is passed.
            let _ = unsafe {
                DwmGetWindowAttribute(
                    hwnd,
                    DWMWA_CLOAKED,
                    (&raw mut cloaked).cast::<c_void>(),
                    u32::try_from(size_of::<u32>()).unwrap_or(4),
                )
            };
            WindowFacts {
                hwnd: hwnd.0 as isize,
                pid,
                process_name: names.get(&pid).cloned().unwrap_or_default(),
                title: title(hwnd),
                visible: true,
                cloaked: cloaked != 0,
                display_affinity: affinity,
                topmost: ex_style & WS_EX_TOPMOST.0 != 0,
                layered: ex_style & WS_EX_LAYERED.0 != 0,
                width: u32::try_from(rect.right.saturating_sub(rect.left)).unwrap_or(0),
                height: u32::try_from(rect.bottom.saturating_sub(rect.top)).unwrap_or(0),
            }
        })
        .collect()
}
