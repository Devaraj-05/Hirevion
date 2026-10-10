//! The monitor against the real machine: SP-11's scripted cases that a test can create.
//!
//! - A window of this process hidden from capture (the monitor is told the interview app is
//!   another process, so this one counts as "other").
//! - A copy of a signed system binary under a new name, recognised by hash and signer.
//!
//! Windows are created off-screen, without activation, and destroyed at once.
#![cfg(windows)]

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::Receiver;
use std::time::{Duration, Instant};

use hv_monitor::{Monitor, MonitorConfig, Observation, SignatureStatus, Watch};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, MSG, PM_REMOVE, PeekMessageW,
    RegisterClassW, SW_SHOWNOACTIVATE, SetWindowDisplayAffinity, ShowWindow, TranslateMessage,
    WDA_EXCLUDEFROMCAPTURE, WINDOW_EX_STYLE, WNDCLASSW, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
    WS_POPUP,
};
use windows::core::{PCWSTR, w};

/// The SP-11 exit bound.
const WITHIN: Duration = Duration::from_secs(2);
/// The first scan hashes and verifies every running executable once.
const READY: Duration = Duration::from_secs(120);

fn quiet(watch: Watch) -> MonitorConfig {
    MonitorConfig {
        // Pretend the interview app is someone else, so this process's windows count.
        interview_pid: 0,
        watch,
        ..MonitorConfig::default()
    }
}

/// Pumps this thread's messages (the helper window lives here) while waiting for a match.
fn wait_for(
    observations: &Receiver<Observation>,
    within: Duration,
    mut wanted: impl FnMut(&Observation) -> bool,
) -> Option<(Observation, Duration)> {
    let started = Instant::now();
    while started.elapsed() < within {
        pump();
        if let Ok(observation) = observations.recv_timeout(Duration::from_millis(20))
            && wanted(&observation)
        {
            return Some((observation, started.elapsed()));
        }
    }
    None
}

fn pump() {
    let mut message = MSG::default();
    // SAFETY: `message` is a live MSG; PeekMessageW with PM_REMOVE fills it for this thread.
    while unsafe { PeekMessageW(&raw mut message, None, 0, 0, PM_REMOVE) }.as_bool() {
        // SAFETY: `message` was just filled by PeekMessageW.
        unsafe {
            let _ = TranslateMessage(&raw const message);
            DispatchMessageW(&raw const message);
        }
    }
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

/// A small off-screen window that never takes focus, destroyed on drop.
struct HelperWindow(HWND);

impl HelperWindow {
    fn create(title: PCWSTR) -> Self {
        // SAFETY: null asks for this executable's module handle.
        let instance = unsafe { GetModuleHandleW(None) }.expect("module handle");
        let class = WNDCLASSW {
            lpfnWndProc: Some(helper_proc),
            hInstance: instance.into(),
            lpszClassName: w!("HvMonitorTestHelper"),
            ..WNDCLASSW::default()
        };
        // SAFETY: `class` is fully initialised; registering twice fails harmlessly.
        let _ = unsafe { RegisterClassW(&raw const class) };
        // SAFETY: the class is registered above; every pointer argument is valid or null.
        let hwnd = unsafe {
            CreateWindowExW(
                WINDOW_EX_STYLE(WS_EX_TOOLWINDOW.0 | WS_EX_NOACTIVATE.0),
                w!("HvMonitorTestHelper"),
                title,
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
        .expect("helper window");
        // SAFETY: `hwnd` is the window just created on this thread.
        let _ = unsafe { ShowWindow(hwnd, SW_SHOWNOACTIVATE) };
        Self(hwnd)
    }
}

impl Drop for HelperWindow {
    fn drop(&mut self) {
        // SAFETY: the window was created on this thread and is destroyed once.
        let _ = unsafe { DestroyWindow(self.0) };
        pump();
    }
}

#[test]
fn a_capture_excluded_window_is_reported_within_two_seconds() {
    let (monitor, observations) = Monitor::start(quiet(Watch {
        windows: true,
        ..Watch::none()
    }))
    .expect("monitor starts");
    assert!(monitor.wait_ready(READY), "the first scan finished");

    let window = HelperWindow::create(w!("Hirevion excluded helper"));
    // SAFETY: `window.0` is a live top-level window owned by this process.
    unsafe { SetWindowDisplayAffinity(window.0, WDA_EXCLUDEFROMCAPTURE) }
        .expect("exclude from capture");
    let me = std::process::id();
    let found = wait_for(&observations, WITHIN, |o| {
        matches!(o, Observation::CaptureExcludedWindow(w)
            if w.pid == me && w.window_title == "Hirevion excluded helper")
    });
    drop(window);
    monitor.stop();

    let (observation, after) = found.expect("CAPTURE_EXCLUDED_WINDOW within 2 s");
    let Observation::CaptureExcludedWindow(sighting) = observation else {
        unreachable!()
    };
    assert_eq!(sighting.display_affinity, 0x11);
    assert!(after <= WITHIN, "took {after:?}");
}

struct Copied {
    path: PathBuf,
    child: Option<Child>,
}

impl Drop for Copied {
    fn drop(&mut self) {
        if let Some(child) = &mut self.child {
            let _ = child.kill();
            let _ = child.wait();
        }
        let _ = std::fs::remove_dir_all(self.path.parent().expect("parent"));
    }
}

fn system32(file: &str) -> PathBuf {
    let root = std::env::var_os("SystemRoot").unwrap_or_else(|| r"C:\Windows".into());
    PathBuf::from(root).join("System32").join(file)
}

#[test]
fn a_renamed_signed_binary_is_reported_with_its_hash_and_signer_within_two_seconds() {
    let original = system32("PING.EXE");
    let dir = std::env::temp_dir().join(format!("hv-monitor-renamed-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("temp dir");
    let renamed = dir.join("study-notes-viewer.exe");
    std::fs::copy(&original, &renamed).expect("copy the signed binary");
    let mut copied = Copied {
        path: renamed.clone(),
        child: None,
    };

    let (monitor, observations) = Monitor::start(quiet(Watch {
        processes: true,
        ..Watch::none()
    }))
    .expect("monitor starts");
    assert!(monitor.wait_ready(READY), "the first scan finished");

    let child = Command::new(&renamed)
        .args(["-n", "30", "127.0.0.1"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("start the renamed copy");
    let pid = child.id();
    copied.child = Some(child);
    let found = wait_for(
        &observations,
        WITHIN,
        |o| matches!(o, Observation::ProcessStarted { process, .. } if process.pid == pid),
    );
    monitor.stop();

    let (observation, after) = found.expect("the renamed process within 2 s");
    let Observation::ProcessStarted {
        at_start, process, ..
    } = observation
    else {
        unreachable!()
    };
    assert!(!at_start);
    assert!(after <= WITHIN, "took {after:?}");
    assert_eq!(process.name.to_lowercase(), "study-notes-viewer.exe");
    assert!(
        process
            .path
            .as_deref()
            .is_some_and(|p| p.to_lowercase().ends_with("study-notes-viewer.exe")),
        "{process:?}"
    );
    assert_eq!(
        process.sha256.as_deref(),
        Some(
            hv_monitor::file_cache::sha256_file(&original)
                .expect("hash the original")
                .as_str()
        ),
        "the hash identifies the binary whatever its name"
    );
    assert_eq!(
        process.signature.status,
        SignatureStatus::Valid,
        "{process:?}"
    );
    assert!(
        process
            .signature
            .signer
            .as_deref()
            .is_some_and(|s| s.contains("Microsoft")),
        "{process:?}"
    );
    assert_eq!(
        process
            .signature
            .signer_cert_sha256
            .as_deref()
            .map(str::len),
        Some(64)
    );
    assert!(process.start_time_ms.is_some());
    assert!(!process.interview_app);
}

#[test]
fn startup_integrity_findings_and_the_vm_check_are_reported() {
    let (monitor, observations) = Monitor::start(MonitorConfig {
        startup_integrity: vec![(
            "webview_environment".to_owned(),
            Some("WEBVIEW2_USER_DATA_FOLDER".to_owned()),
        )],
        ..quiet(Watch {
            integrity: true,
            virtual_machine: true,
            ..Watch::none()
        })
    })
    .expect("monitor starts");
    assert!(monitor.wait_ready(READY));
    let found = wait_for(
        &observations,
        WITHIN,
        |o| matches!(o, Observation::ClientIntegrity(f) if f.reason == "webview_environment"),
    );
    monitor.stop();
    assert!(found.is_some());
}

#[test]
fn the_focus_and_display_watchers_start_and_stop_cleanly() {
    let (monitor, observations) = Monitor::start(quiet(Watch {
        focus: true,
        displays: true,
        devices: true,
        remote_session: true,
        ..Watch::none()
    }))
    .expect("monitor starts");
    assert!(monitor.wait_ready(READY));
    let started = Instant::now();
    monitor.stop();
    assert!(started.elapsed() < Duration::from_secs(5), "stop is prompt");
    // Whatever was seen is well-formed and the channel closes once the threads end.
    for observation in observations.iter() {
        assert!(observation.at_ms() > 0);
    }
}
