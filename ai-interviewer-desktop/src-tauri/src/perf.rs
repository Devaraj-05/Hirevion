//! CPU time of the app's whole process tree: the app itself plus the WebView2 browser,
//! GPU, renderer and utility processes it starts.

use std::time::Duration;

/// `root` and every process descended from it in `table` (`(pid, parent pid)` pairs).
/// Safe against the parent cycles that reused process IDs can create.
#[must_use]
pub fn descendants(root: u32, table: &[(u32, u32)]) -> Vec<u32> {
    let mut found = vec![root];
    let mut next = 0;
    while next < found.len() {
        let parent = found[next];
        for &(pid, parent_pid) in table {
            if parent_pid == parent && !found.contains(&pid) {
                found.push(pid);
            }
        }
        next += 1;
    }
    found
}

/// CPU use as a percentage of all logical processors over `wall`.
#[must_use]
pub fn cpu_percent(cpu_ticks: u64, wall: Duration) -> f64 {
    let processors = std::thread::available_parallelism().map_or(1, std::num::NonZero::get);
    #[allow(clippy::cast_precision_loss)] // Tick counts and core counts are far below 2^52.
    let (cpu, cores) = (cpu_ticks as f64 / 10_000_000.0, processors as f64);
    let capacity = wall.as_secs_f64() * cores;
    if capacity == 0.0 {
        0.0
    } else {
        cpu / capacity * 100.0
    }
}

/// Total CPU time (100 ns units) used so far by this process and its descendants.
#[cfg(windows)]
#[must_use]
pub fn tree_cpu_ticks() -> u64 {
    let table = process_table();
    descendants(std::process::id(), &table)
        .into_iter()
        .filter_map(process_cpu_ticks)
        .sum()
}

#[cfg(windows)]
fn process_table() -> Vec<(u32, u32)> {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW,
        TH32CS_SNAPPROCESS,
    };

    let mut table = Vec::new();
    // SAFETY: the snapshot handle is closed below; the entry struct has its size set.
    unsafe {
        let Ok(snapshot) = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) else {
            return table;
        };
        let mut entry = PROCESSENTRY32W {
            dwSize: u32::try_from(size_of::<PROCESSENTRY32W>()).unwrap_or(u32::MAX),
            ..Default::default()
        };
        let mut more = Process32FirstW(snapshot, &raw mut entry).is_ok();
        while more {
            table.push((entry.th32ProcessID, entry.th32ParentProcessID));
            more = Process32NextW(snapshot, &raw mut entry).is_ok();
        }
        let _ = CloseHandle(snapshot);
    }
    table
}

#[cfg(windows)]
fn process_cpu_ticks(pid: u32) -> Option<u64> {
    use windows::Win32::Foundation::{CloseHandle, FILETIME};
    use windows::Win32::System::Threading::{
        GetProcessTimes, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    fn ticks(time: FILETIME) -> u64 {
        (u64::from(time.dwHighDateTime) << 32) | u64::from(time.dwLowDateTime)
    }
    // SAFETY: the process handle is closed below; the out-parameters are locals.
    unsafe {
        let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let (mut created, mut exited) = (FILETIME::default(), FILETIME::default());
        let (mut kernel, mut user) = (FILETIME::default(), FILETIME::default());
        let times = GetProcessTimes(
            process,
            &raw mut created,
            &raw mut exited,
            &raw mut kernel,
            &raw mut user,
        );
        let _ = CloseHandle(process);
        times.ok().map(|()| ticks(kernel) + ticks(user))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_every_descendant_of_the_root() {
        // (pid, parent)
        let table = [(1, 0), (10, 1), (11, 10), (12, 10), (20, 2), (13, 11)];
        let mut tree = descendants(1, &table);
        tree.sort_unstable();
        assert_eq!(tree, vec![1, 10, 11, 12, 13]);
    }

    #[test]
    fn survives_parent_cycles_from_reused_process_ids() {
        let table = [(1, 3), (2, 1), (3, 2)];
        let mut tree = descendants(1, &table);
        tree.sort_unstable();
        assert_eq!(tree, vec![1, 2, 3]);
    }

    #[test]
    fn a_root_without_children_is_just_itself() {
        assert_eq!(descendants(7, &[(1, 0)]), vec![7]);
    }
}
