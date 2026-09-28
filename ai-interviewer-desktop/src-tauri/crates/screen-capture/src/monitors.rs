//! Display enumeration.

use crate::geometry::Size;
use windows::Win32::Foundation::{LPARAM, RECT};
use windows::Win32::Graphics::Gdi::{
    EnumDisplayMonitors, GetMonitorInfoW, HDC, HMONITOR, MONITORINFOEXW,
};
use windows_core::{BOOL, Error, Result};

/// `MONITORINFO::dwFlags` bit for the primary display (from WinUser.h; defined here to
/// avoid pulling in the whole `WindowsAndMessaging` bindings).
const MONITORINFOF_PRIMARY: u32 = 1;

/// A connected display. `handle` is the raw `HMONITOR` value, kept as an integer so the
/// description can move between threads; it stays valid while the display is connected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MonitorInfo {
    pub handle: isize,
    pub name: String,
    /// Size in the calling thread's DPI awareness; capture uses the WGC item's own size.
    pub size: Size,
    pub primary: bool,
}

impl MonitorInfo {
    #[must_use]
    pub fn hmonitor(&self) -> HMONITOR {
        HMONITOR(self.handle as *mut core::ffi::c_void)
    }
}

/// Every connected display, in the order Windows reports them.
pub fn enumerate() -> Result<Vec<MonitorInfo>> {
    unsafe extern "system" fn collect(
        monitor: HMONITOR,
        _: HDC,
        _: *mut RECT,
        data: LPARAM,
    ) -> BOOL {
        // SAFETY: `data` is the address of the Vec below, which outlives the enumeration.
        let handles = unsafe { &mut *(data.0 as *mut Vec<HMONITOR>) };
        handles.push(monitor);
        BOOL::from(true)
    }

    let mut handles: Vec<HMONITOR> = Vec::new();
    // SAFETY: the callback only pushes into `handles`, which lives until the call returns.
    let ok = unsafe {
        EnumDisplayMonitors(None, None, Some(collect), LPARAM(&raw mut handles as isize))
    };
    if !ok.as_bool() {
        return Err(Error::from_thread());
    }
    handles.into_iter().map(describe).collect()
}

fn describe(monitor: HMONITOR) -> Result<MonitorInfo> {
    let mut info = MONITORINFOEXW::default();
    info.monitorInfo.cbSize = u32::try_from(size_of::<MONITORINFOEXW>()).unwrap_or(u32::MAX);
    // SAFETY: `info` is a MONITORINFOEXW whose cbSize says so, as GetMonitorInfoW requires.
    let ok = unsafe { GetMonitorInfoW(monitor, &raw mut info.monitorInfo) };
    if !ok.as_bool() {
        return Err(Error::from_thread());
    }
    let rect = info.monitorInfo.rcMonitor;
    let end = info
        .szDevice
        .iter()
        .position(|&c| c == 0)
        .unwrap_or(info.szDevice.len());
    Ok(MonitorInfo {
        handle: monitor.0 as isize,
        name: String::from_utf16_lossy(&info.szDevice[..end]),
        size: Size {
            width: u32::try_from(rect.right - rect.left).unwrap_or(0),
            height: u32::try_from(rect.bottom - rect.top).unwrap_or(0),
        },
        primary: info.monitorInfo.dwFlags & MONITORINFOF_PRIMARY != 0,
    })
}
