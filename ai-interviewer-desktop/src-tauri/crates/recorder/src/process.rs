//! CPU and memory figures for the current process.

use std::time::Instant;
use windows::Win32::Foundation::FILETIME;
use windows::Win32::System::ProcessStatus::{GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS};
use windows::Win32::System::SystemInformation::{GetSystemInfo, SYSTEM_INFO};
use windows::Win32::System::Threading::{GetCurrentProcess, GetProcessTimes};
use windows_core::Result;

/// CPU time used by this process (100 ns units) at a moment in time.
#[derive(Debug, Clone, Copy)]
pub struct CpuSnapshot {
    pub cpu_ticks: u64,
    pub at: Instant,
}

pub fn cpu_snapshot() -> Result<CpuSnapshot> {
    let mut creation = FILETIME::default();
    let mut exit = FILETIME::default();
    let mut kernel = FILETIME::default();
    let mut user = FILETIME::default();
    // SAFETY: the pseudo-handle is always valid and the out-pointers refer to locals.
    unsafe {
        GetProcessTimes(
            GetCurrentProcess(),
            &raw mut creation,
            &raw mut exit,
            &raw mut kernel,
            &raw mut user,
        )?;
    }
    Ok(CpuSnapshot {
        cpu_ticks: ticks(kernel) + ticks(user),
        at: Instant::now(),
    })
}

/// Logical processors (hardware threads) in the machine.
#[must_use]
pub fn logical_processors() -> u32 {
    let mut info = SYSTEM_INFO::default();
    // SAFETY: GetSystemInfo fills the struct and cannot fail.
    unsafe { GetSystemInfo(&raw mut info) };
    info.dwNumberOfProcessors
}

/// The largest working set this process has had, in bytes.
pub fn peak_working_set_bytes() -> Result<usize> {
    let size = u32::try_from(size_of::<PROCESS_MEMORY_COUNTERS>()).unwrap_or(u32::MAX);
    let mut counters = PROCESS_MEMORY_COUNTERS {
        cb: size,
        ..Default::default()
    };
    // SAFETY: `counters` is correctly sized for the call.
    unsafe { GetProcessMemoryInfo(GetCurrentProcess(), &raw mut counters, size)? };
    Ok(counters.PeakWorkingSetSize)
}

fn ticks(time: FILETIME) -> u64 {
    (u64::from(time.dwHighDateTime) << 32) | u64::from(time.dwLowDateTime)
}
