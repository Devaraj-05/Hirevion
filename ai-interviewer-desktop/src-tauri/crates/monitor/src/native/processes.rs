//! The process list (Toolhelp) and §60's metadata for one process.

use std::path::Path;

use windows::Win32::Foundation::FILETIME;
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Threading::{
    GetProcessTimes, OpenProcess, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
    QueryFullProcessImageNameW,
};
use windows::core::PWSTR;

use super::{OwnedHandle, from_wide};
use crate::file_cache::FileCache;
use crate::observation::{ProcessInfo, SignatureInfo};
use crate::track::ProcessEntry;

/// Milliseconds between 1601-01-01 (FILETIME's epoch) and 1970-01-01.
const FILETIME_UNIX_OFFSET_MS: i64 = 11_644_473_600_000;

/// Every running process: PID, parent PID and executable name.
pub(crate) fn snapshot() -> Vec<ProcessEntry> {
    // SAFETY: takes flags and a PID only; the returned handle is owned below.
    let Ok(handle) = (unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }) else {
        return Vec::new();
    };
    let snapshot = OwnedHandle(handle);
    let mut entry = PROCESSENTRY32W {
        dwSize: u32::try_from(size_of::<PROCESSENTRY32W>()).unwrap_or(u32::MAX),
        ..PROCESSENTRY32W::default()
    };
    let mut entries = Vec::with_capacity(512);
    // SAFETY: the snapshot handle is open and `entry` is a live PROCESSENTRY32W whose dwSize
    // is set, as Process32FirstW/NextW require.
    let mut more = unsafe { Process32FirstW(snapshot.0, &raw mut entry) }.is_ok();
    while more {
        entries.push(ProcessEntry {
            pid: entry.th32ProcessID,
            parent_pid: entry.th32ParentProcessID,
            name: from_wide(&entry.szExeFile),
        });
        // SAFETY: as above.
        more = unsafe { Process32NextW(snapshot.0, &raw mut entry) }.is_ok();
    }
    entries
}

/// §60's metadata for a newly seen process. `offset_ms` turns this machine's clock into the
/// monitor's clock (server time).
pub(crate) fn describe(
    entry: &ProcessEntry,
    window_titles: Vec<String>,
    interview_app: bool,
    cache: &mut FileCache,
    offset_ms: i64,
) -> ProcessInfo {
    let (path, started) = open_details(entry.pid);
    let facts = path.as_deref().map(|p| cache.facts(Path::new(p)));
    let (sha256, signature) = facts.map_or((None, SignatureInfo::default()), |f| {
        (f.sha256, f.signature)
    });
    ProcessInfo {
        pid: entry.pid,
        parent_pid: entry.parent_pid,
        name: entry.name.clone(),
        path,
        start_time_ms: started.map(|ms| ms.saturating_add(offset_ms)),
        window_titles,
        sha256,
        signature,
        interview_app,
    }
}

/// The executable path and start time (this machine's clock), when the process can be
/// opened. Protected processes and the System process can't, and keep only their name.
pub(crate) fn open_details(pid: u32) -> (Option<String>, Option<i64>) {
    if pid == 0 || pid == 4 {
        return (None, None);
    }
    // SAFETY: takes an access mask, a flag and a PID; the handle is owned below.
    let Ok(handle) = (unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }) else {
        return (None, None);
    };
    let process = OwnedHandle(handle);
    (image_path(&process), start_time(&process))
}

/// The full Win32 path of the process's executable.
pub(crate) fn image_path(process: &OwnedHandle) -> Option<String> {
    let mut buffer = vec![0u16; 32_768];
    let mut length = u32::try_from(buffer.len()).unwrap_or(u32::MAX);
    // SAFETY: `buffer` holds `length` UTF-16 units and outlives the call; the API writes at
    // most that many and updates `length`.
    unsafe {
        QueryFullProcessImageNameW(
            process.0,
            PROCESS_NAME_WIN32,
            PWSTR(buffer.as_mut_ptr()),
            &raw mut length,
        )
    }
    .ok()?;
    let length = usize::try_from(length).ok()?.min(buffer.len());
    Some(String::from_utf16_lossy(&buffer[..length]))
}

fn start_time(process: &OwnedHandle) -> Option<i64> {
    let mut created = FILETIME::default();
    let mut exited = FILETIME::default();
    let mut kernel = FILETIME::default();
    let mut user = FILETIME::default();
    // SAFETY: the process handle is open with query rights; the four out-pointers refer to
    // live locals for the duration of the call.
    unsafe {
        GetProcessTimes(
            process.0,
            &raw mut created,
            &raw mut exited,
            &raw mut kernel,
            &raw mut user,
        )
    }
    .ok()?;
    let ticks = (u64::from(created.dwHighDateTime) << 32) | u64::from(created.dwLowDateTime);
    let ms = i64::try_from(ticks / 10_000).ok()?;
    Some(ms - FILETIME_UNIX_OFFSET_MS)
}
