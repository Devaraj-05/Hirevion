//! The process list on demand, for the check before Start (ADR-0046), on the real machine.
#![cfg(windows)]

use std::time::Instant;

use hv_monitor::running_processes;

#[test]
fn every_running_process_is_described_and_this_one_is_the_interview_app() {
    let started = Instant::now();
    let processes = running_processes(std::process::id(), true, &|_| false);
    let elapsed = started.elapsed();
    assert!(processes.len() > 10, "{} processes", processes.len());
    let this = processes
        .iter()
        .find(|p| p.pid == std::process::id())
        .expect("this process");
    assert!(this.interview_app && this.path.is_some() && this.sha256.is_some());
    assert!(processes.iter().any(|p| !p.interview_app));
    // Without hashes (no rule matches by hash), the signatures alone are read.
    let quick = running_processes(std::process::id(), false, &|_| false);
    assert!(quick.iter().all(|p| p.sha256.is_none()));
    let this = quick
        .iter()
        .find(|p| p.pid == std::process::id())
        .expect("this process");
    assert!(this.path.is_some());
    println!(
        "{} processes described in {} ms",
        processes.len(),
        elapsed.as_millis()
    );
}
