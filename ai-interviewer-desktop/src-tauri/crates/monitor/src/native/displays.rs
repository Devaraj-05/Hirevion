//! Connected displays (§63).

use windows::Win32::Foundation::{LPARAM, RECT};
use windows::Win32::Graphics::Gdi::{
    EnumDisplayMonitors, GetMonitorInfoW, HDC, HMONITOR, MONITORINFOEXW,
};
use windows_core::BOOL;

use super::from_wide;
use crate::observation::DisplayInfo;

/// `MONITORINFO::dwFlags` bit for the primary display.
const MONITORINFOF_PRIMARY: u32 = 1;

/// Every connected display, by GDI device name. `None` when the list couldn't be read (a
/// failed scan must not look like every display disconnecting).
pub(crate) fn enumerate() -> Option<Vec<DisplayInfo>> {
    unsafe extern "system" fn collect(
        monitor: HMONITOR,
        _: HDC,
        _: *mut RECT,
        data: LPARAM,
    ) -> BOOL {
        // SAFETY: `data` is the address of the Vec in `enumerate`, which outlives the call.
        let monitors = unsafe { &mut *(data.0 as *mut Vec<HMONITOR>) };
        monitors.push(monitor);
        BOOL::from(true)
    }
    let mut monitors: Vec<HMONITOR> = Vec::new();
    // SAFETY: the callback only pushes into `monitors`, which lives until the call returns.
    let listed = unsafe {
        EnumDisplayMonitors(
            None,
            None,
            Some(collect),
            LPARAM(&raw mut monitors as isize),
        )
    };
    if !listed.as_bool() {
        return None;
    }
    let mut displays: Vec<DisplayInfo> = monitors.into_iter().filter_map(describe).collect();
    displays.sort_by(|a, b| a.name.cmp(&b.name));
    Some(displays)
}

fn describe(monitor: HMONITOR) -> Option<DisplayInfo> {
    let mut info = MONITORINFOEXW::default();
    info.monitorInfo.cbSize = u32::try_from(size_of::<MONITORINFOEXW>()).unwrap_or(u32::MAX);
    // SAFETY: `info` is a MONITORINFOEXW whose cbSize says so, as GetMonitorInfoW requires.
    if !unsafe { GetMonitorInfoW(monitor, &raw mut info.monitorInfo) }.as_bool() {
        return None;
    }
    let rect = info.monitorInfo.rcMonitor;
    Some(DisplayInfo {
        name: from_wide(&info.szDevice),
        x: rect.left,
        y: rect.top,
        width: u32::try_from(rect.right.saturating_sub(rect.left)).unwrap_or(0),
        height: u32::try_from(rect.bottom.saturating_sub(rect.top)).unwrap_or(0),
        primary: info.monitorInfo.dwFlags & MONITORINFOF_PRIMARY != 0,
    })
}
