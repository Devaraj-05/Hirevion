//! SP-11 exit criteria end to end on the real machine: the monitor feeds the device rules,
//! and the event lands in the durable queue with its `seq`, within 2 s of the cause.
//!
//! - a blocked process (matched by path);
//! - a renamed blocked binary (matched by hash, not by name);
//! - a capture-excluded window.
//!
//! (A second monitor is covered by the display tracker and rule tests with fakes.)
#![cfg(windows)]

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::Receiver;
use std::time::{Duration, Instant};

use hv_event_queue::{
    AppRules, DeviceRules, EventName, EventQueue, PolicyMatcher, ProctorEvent, Thresholds,
};
use hv_monitor::{Monitor, MonitorConfig, Observation, Watch};
use serde_json::json;
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, MSG, PM_REMOVE, PeekMessageW,
    RegisterClassW, SW_SHOWNOACTIVATE, SetWindowDisplayAffinity, ShowWindow,
    WDA_EXCLUDEFROMCAPTURE, WINDOW_EX_STYLE, WNDCLASSW, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
    WS_POPUP,
};
use windows::core::w;

const WITHIN: Duration = Duration::from_secs(2);
const READY: Duration = Duration::from_secs(120);

struct Scratch {
    dir: PathBuf,
    children: Vec<Child>,
}

impl Scratch {
    fn new(name: &str) -> Self {
        let dir = std::env::temp_dir().join(format!("hv-e2e-{name}-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("scratch dir");
        Self {
            dir,
            children: Vec::new(),
        }
    }

    fn spawn(&mut self, program: &PathBuf) -> u32 {
        let child = Command::new(program)
            .args(["-n", "30", "127.0.0.1"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn");
        let pid = child.id();
        self.children.push(child);
        pid
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        for child in &mut self.children {
            let _ = child.kill();
            let _ = child.wait();
        }
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn ping() -> PathBuf {
    let root = std::env::var_os("SystemRoot").unwrap_or_else(|| r"C:\Windows".into());
    PathBuf::from(root).join("System32").join("PING.EXE")
}

fn rules_for(app_rules: serde_json::Value) -> DeviceRules {
    let app_rules: AppRules = serde_json::from_value(app_rules).expect("rules");
    DeviceRules::new(PolicyMatcher::new(&app_rules), Thresholds::default(), false)
}

fn pump() {
    let mut message = MSG::default();
    // SAFETY: `message` is a live MSG; PeekMessageW with PM_REMOVE fills it for this thread.
    while unsafe { PeekMessageW(&raw mut message, None, 0, 0, PM_REMOVE) }.as_bool() {
        // SAFETY: `message` was just filled by PeekMessageW.
        unsafe { DispatchMessageW(&raw const message) };
    }
}

/// Feeds observations through `rules` into `queue` until `wanted` matches a queued event.
fn wait_for_event(
    observations: &Receiver<Observation>,
    rules: &mut [&mut DeviceRules],
    queue: &EventQueue,
    within: Duration,
    mut wanted: impl FnMut(&ProctorEvent) -> bool,
) -> Option<(ProctorEvent, Duration)> {
    let started = Instant::now();
    while started.elapsed() < within {
        pump();
        let Ok(observation) = observations.recv_timeout(Duration::from_millis(20)) else {
            continue;
        };
        for rule in rules.iter_mut() {
            for event in queue
                .append_all(rule.observe(&observation))
                .expect("append")
            {
                if wanted(&event) {
                    return Some((event, started.elapsed()));
                }
            }
        }
    }
    None
}

fn start(watch: Watch) -> (hv_monitor::MonitorHandle, Receiver<Observation>) {
    let (monitor, observations) = Monitor::start(MonitorConfig {
        interview_pid: 0,
        watch,
        ..MonitorConfig::default()
    })
    .expect("monitor");
    assert!(monitor.wait_ready(READY), "first scan");
    // Drop what the first scan reported.
    while observations.try_recv().is_ok() {}
    (monitor, observations)
}

#[test]
fn a_blocked_process_and_a_renamed_blocked_binary_are_queued_within_two_seconds() {
    let mut scratch = Scratch::new("blocked");
    let renamed = scratch.dir.join("calculator-helper.exe");
    std::fs::copy(ping(), &renamed).expect("copy");
    let hash = hv_monitor::file_cache::sha256_file(&ping()).expect("hash");
    let queue = EventQueue::open(&scratch.dir.join("queue"), "e2e-blocked").expect("queue");
    let mut by_path = rules_for(json!({
        "blocked": [ { "match": "path", "value": ping().display().to_string(), "category": "network_tools" } ]
    }));
    let mut by_hash = rules_for(json!({ "blocked": [ { "match": "hash", "value": hash } ] }));

    let (monitor, observations) = start(Watch {
        processes: true,
        ..Watch::none()
    });

    let original = scratch.spawn(&ping());
    let found = wait_for_event(&observations, &mut [&mut by_path], &queue, WITHIN, |e| {
        e.event == EventName::BlockedProcessDetected && e.details["pid"] == original
    });
    let (event, after) = found.expect("BLOCKED_PROCESS_DETECTED for the blocked path");
    assert!(after <= WITHIN, "took {after:?}");
    assert_eq!(event.details["matched_by"], "path");
    assert_eq!(event.details["severity_hint"], "critical");
    assert!(event.seq >= 1);

    let copy = scratch.spawn(&renamed);
    let found = wait_for_event(&observations, &mut [&mut by_hash], &queue, WITHIN, |e| {
        e.event == EventName::BlockedProcessDetected && e.details["pid"] == copy
    });
    monitor.stop();
    let (event, after) = found.expect("BLOCKED_PROCESS_DETECTED for the renamed binary");
    assert!(after <= WITHIN, "took {after:?}");
    assert_eq!(event.details["matched_by"], "hash");
    assert_eq!(event.details["name"], "calculator-helper.exe");
    assert_eq!(
        event.details["publisher"]
            .as_str()
            .map(|p| p.contains("Microsoft")),
        Some(true)
    );
}

unsafe extern "system" fn helper_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    // SAFETY: forwards the window procedure's own arguments unchanged.
    unsafe { DefWindowProcW(hwnd, message, wparam, lparam) }
}

#[test]
fn a_capture_excluded_window_is_queued_within_two_seconds() {
    let scratch = Scratch::new("excluded");
    let queue = EventQueue::open(&scratch.dir.join("queue"), "e2e-excluded").expect("queue");
    let mut rules = rules_for(json!({}));
    let (monitor, observations) = start(Watch {
        windows: true,
        ..Watch::none()
    });

    // SAFETY: null asks for this executable's module handle.
    let instance = unsafe { GetModuleHandleW(None) }.expect("module");
    let class = WNDCLASSW {
        lpfnWndProc: Some(helper_proc),
        hInstance: instance.into(),
        lpszClassName: w!("HvQueueTestHelper"),
        ..WNDCLASSW::default()
    };
    // SAFETY: `class` is fully initialised; registering twice fails harmlessly.
    let _ = unsafe { RegisterClassW(&raw const class) };
    // SAFETY: the class is registered; every pointer argument is valid or null. The window is
    // off-screen and never activated.
    let hwnd = unsafe {
        CreateWindowExW(
            WINDOW_EX_STYLE(WS_EX_TOOLWINDOW.0 | WS_EX_NOACTIVATE.0),
            w!("HvQueueTestHelper"),
            w!("Hirevion queue excluded helper"),
            WS_POPUP,
            -12_000,
            -12_000,
            160,
            120,
            None,
            None,
            Some(instance.into()),
            None,
        )
    }
    .expect("window");
    // SAFETY: `hwnd` is the window just created on this thread.
    let _ = unsafe { ShowWindow(hwnd, SW_SHOWNOACTIVATE) };
    // SAFETY: as above; the window belongs to this process.
    unsafe { SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE) }.expect("affinity");

    let me = std::process::id();
    let found = wait_for_event(&observations, &mut [&mut rules], &queue, WITHIN, |e| {
        e.event == EventName::CaptureExcludedWindow && e.details["pid"] == me
    });
    // SAFETY: destroys the window created above, on its own thread, once.
    let _ = unsafe { DestroyWindow(hwnd) };
    pump();
    monitor.stop();

    let (event, after) = found.expect("CAPTURE_EXCLUDED_WINDOW");
    assert!(after <= WITHIN, "took {after:?}");
    assert_eq!(event.details["display_affinity"], "exclude_from_capture");
    assert_eq!(
        event.details["window_title"],
        "Hirevion queue excluded helper"
    );
}
