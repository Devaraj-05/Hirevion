//! Processor, memory, disk, displays and the Windows build.

use super::describe;
use super::registry::{read_dword, read_string};
use crate::classify::{
    CpuTimes, busy_percent, classify_cpu, classify_disk, classify_displays, classify_memory,
    classify_os,
};
use crate::result::{CheckResult, Status, names};
use std::os::windows::ffi::OsStrExt;
use std::time::Duration;
use windows::Win32::Foundation::FILETIME;
use windows::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
use windows::Win32::System::Registry::HKEY_LOCAL_MACHINE;
use windows::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};
use windows::Win32::System::Threading::{
    ALL_PROCESSOR_GROUPS, GetActiveProcessorCount, GetSystemTimes,
};
use windows::core::PCWSTR;

/// How long the processor load is sampled.
const CPU_SAMPLE: Duration = Duration::from_millis(500);
const CURRENT_VERSION: &str = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion";

/// Logical processors across every processor group, and how busy they were over
/// [`CPU_SAMPLE`].
pub(super) fn cpu() -> CheckResult {
    // SAFETY: takes a group number only; ALL_PROCESSOR_GROUPS asks for every group.
    let mut logical = unsafe { GetActiveProcessorCount(ALL_PROCESSOR_GROUPS) };
    if logical == 0 {
        logical = std::thread::available_parallelism()
            .ok()
            .and_then(|count| u32::try_from(count.get()).ok())
            .unwrap_or(0);
    }
    let sampled = system_times().and_then(|before| {
        std::thread::sleep(CPU_SAMPLE);
        system_times().map(|after| busy_percent(before, after))
    });
    match sampled {
        Ok(busy) => classify_cpu(logical, busy),
        Err(error) => CheckResult::new(names::CPU, Status::Warn)
            .with_value(format!("{logical} logical"))
            .with_detail(format!(
                "The processor load could not be read: {}",
                describe(&error)
            )),
    }
}

fn system_times() -> windows::core::Result<CpuTimes> {
    let mut idle = FILETIME::default();
    let mut kernel = FILETIME::default();
    let mut user = FILETIME::default();
    // SAFETY: the three out-pointers refer to live locals for the duration of the call.
    unsafe {
        GetSystemTimes(
            Some(&raw mut idle),
            Some(&raw mut kernel),
            Some(&raw mut user),
        )
    }?;
    Ok(CpuTimes {
        idle: ticks(idle),
        kernel: ticks(kernel),
        user: ticks(user),
    })
}

fn ticks(time: FILETIME) -> u64 {
    (u64::from(time.dwHighDateTime) << 32) | u64::from(time.dwLowDateTime)
}

/// Physical memory available to start new work.
pub(super) fn memory() -> CheckResult {
    let mut status = MEMORYSTATUSEX {
        dwLength: u32::try_from(size_of::<MEMORYSTATUSEX>()).unwrap_or(u32::MAX),
        ..MEMORYSTATUSEX::default()
    };
    // SAFETY: `status` is a live MEMORYSTATUSEX whose dwLength is set, as the API requires.
    match unsafe { GlobalMemoryStatusEx(&raw mut status) } {
        Ok(()) => classify_memory(status.ullAvailPhys),
        Err(error) => CheckResult::new(names::MEMORY, Status::Warn)
            .with_value("unknown")
            .with_detail(format!(
                "Free memory could not be read: {}",
                describe(&error)
            )),
    }
}

/// Free space, within the user's quota, on the drive that holds `%LOCALAPPDATA%`, where the
/// app keeps its recordings until they upload.
pub(super) fn disk() -> CheckResult {
    let unknown = |detail: String| {
        CheckResult::new(names::DISK, Status::Warn)
            .with_value("unknown")
            .with_detail(detail)
    };
    let Some(folder) = std::env::var_os("LOCALAPPDATA") else {
        return unknown("Free disk space could not be read: LOCALAPPDATA is not set.".to_owned());
    };
    let path: Vec<u16> = folder.encode_wide().chain(std::iter::once(0)).collect();
    let mut free = 0u64;
    // SAFETY: `path` is NUL-terminated and outlives the call; the out-pointer refers to a
    // live local and the totals we don't need are passed as null.
    let read =
        unsafe { GetDiskFreeSpaceExW(PCWSTR(path.as_ptr()), Some(&raw mut free), None, None) };
    match read {
        Ok(()) => classify_disk(free),
        Err(error) => unknown(format!(
            "Free disk space could not be read: {}",
            describe(&error)
        )),
    }
}

/// Connected displays. The check warns about extra displays; a single-display interview
/// policy turns that into a failure on the server's side.
pub(super) fn displays() -> CheckResult {
    match hv_screen_capture::monitors::enumerate() {
        Ok(monitors) => classify_displays(monitors.len(), false),
        Err(error) => CheckResult::new(names::DISPLAYS, Status::Fail)
            .with_value("unknown")
            .with_detail(format!(
                "The displays could not be listed: {}",
                describe(&error)
            )),
    }
}

/// The build and update revision from the registry, which compatibility shims don't
/// change (unlike `GetVersionEx`).
pub(super) fn os() -> CheckResult {
    let build = read_string(HKEY_LOCAL_MACHINE, CURRENT_VERSION, "CurrentBuild")
        .and_then(|build| build.trim().parse::<u32>().ok());
    let ubr = read_dword(HKEY_LOCAL_MACHINE, CURRENT_VERSION, "UBR");
    match build {
        Some(build) => classify_os(build, ubr),
        None => CheckResult::new(names::OS, Status::Warn)
            .with_value("Windows (unknown build)")
            .with_detail("The Windows build could not be read."),
    }
}
