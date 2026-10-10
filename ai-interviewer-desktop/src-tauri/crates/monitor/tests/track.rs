//! The pure trackers that turn successive scans into observations, driven with fakes.

use std::collections::HashMap;

use hv_monitor::track::{
    DeviceTracker, DisplayTracker, ProcessEntry, ProcessTracker, RemoteTracker, WindowFacts,
    WindowTracker, interview_tree,
};
use hv_monitor::{
    CaptureDevice, DeviceChangeKind, DeviceKind, DisplayChangeKind, DisplayInfo, Observation,
    ProcessInfo, SignatureInfo, VirtualDeviceCatalogue,
};

fn display(name: &str, width: u32, height: u32, primary: bool) -> DisplayInfo {
    DisplayInfo {
        name: name.to_owned(),
        x: 0,
        y: 0,
        width,
        height,
        primary,
    }
}

#[test]
fn a_single_display_at_start_is_quiet() {
    let mut tracker = DisplayTracker::default();
    assert!(
        tracker
            .update(1, vec![display(r"\\.\DISPLAY1", 1920, 1080, true)])
            .is_empty()
    );
}

#[test]
fn several_displays_at_start_are_reported() {
    let mut tracker = DisplayTracker::default();
    let seen = tracker.update(
        1,
        vec![
            display(r"\\.\DISPLAY1", 1920, 1080, true),
            display(r"\\.\DISPLAY2", 1280, 1024, false),
        ],
    );
    assert_eq!(seen.len(), 1);
    let Observation::DisplayChanged(change) = &seen[0] else {
        panic!("{seen:?}")
    };
    assert_eq!(change.change, DisplayChangeKind::PresentAtStart);
    assert_eq!(change.display_count, 2);
    assert_eq!(seen[0].contract_event(), Some("EXTERNAL_DISPLAY_CHANGE"));
}

#[test]
fn plugging_in_unplugging_and_resizing_a_display_are_each_reported() {
    let mut tracker = DisplayTracker::default();
    let one = display(r"\\.\DISPLAY1", 1920, 1080, true);
    let two = display(r"\\.\DISPLAY2", 2560, 1440, false);
    tracker.update(1, vec![one.clone()]);

    let plugged = tracker.update(2, vec![one.clone(), two.clone()]);
    assert_eq!(plugged.len(), 1);
    let Observation::DisplayChanged(change) = &plugged[0] else {
        panic!("{plugged:?}")
    };
    assert_eq!(change.change, DisplayChangeKind::Connected);
    assert_eq!(change.display, two);
    assert_eq!((change.previous_count, change.display_count), (1, 2));
    assert_eq!(change.at_ms, 2);

    let resized = display(r"\\.\DISPLAY1", 1280, 720, true);
    let changed = tracker.update(3, vec![resized.clone(), two.clone()]);
    let Observation::DisplayChanged(change) = &changed[0] else {
        panic!("{changed:?}")
    };
    assert_eq!(change.change, DisplayChangeKind::Reconfigured);
    assert_eq!(change.previous.as_ref(), Some(&one));
    assert_eq!(change.display, resized);

    let unplugged = tracker.update(4, vec![resized]);
    let Observation::DisplayChanged(change) = &unplugged[0] else {
        panic!("{unplugged:?}")
    };
    assert_eq!(change.change, DisplayChangeKind::Disconnected);
    assert_eq!(change.display, two);
    assert_eq!(change.display_count, 1);

    assert!(
        tracker
            .update(5, vec![display(r"\\.\DISPLAY1", 1280, 720, true)])
            .is_empty()
    );
}

fn camera(id: &str, name: &str) -> CaptureDevice {
    CaptureDevice {
        kind: DeviceKind::Camera,
        id: id.to_owned(),
        name: name.to_owned(),
    }
}

fn microphone(id: &str, name: &str) -> CaptureDevice {
    CaptureDevice {
        kind: DeviceKind::Microphone,
        id: id.to_owned(),
        name: name.to_owned(),
    }
}

#[test]
fn the_virtual_device_catalogue_matches_names_without_case() {
    let catalogue = VirtualDeviceCatalogue::default();
    for name in [
        "OBS Virtual Camera",
        "ManyCam Virtual Webcam",
        "XSplit VCam",
        "Snap Camera",
        "CABLE Output (VB-Audio Virtual Cable)",
        "VoiceMeeter Output (VB-Audio VoiceMeeter VAIO)",
        "obs-camera",
    ] {
        assert!(catalogue.matches(name).is_some(), "{name}");
    }
    for name in [
        "Integrated Camera",
        "Microphone Array (Realtek(R) Audio)",
        "Logitech BRIO",
    ] {
        assert_eq!(catalogue.matches(name), None, "{name}");
    }
    let custom = VirtualDeviceCatalogue::new(["Acme Fake Cam"]);
    assert_eq!(custom.matches("acme fake cam 2"), Some("Acme Fake Cam"));
    assert_eq!(custom.matches("OBS Virtual Camera"), None);
}

#[test]
fn devices_present_at_start_report_only_virtual_ones() {
    let mut tracker = DeviceTracker::new(VirtualDeviceCatalogue::default());
    let seen = tracker.update(
        1,
        vec![
            camera("cam-1", "Integrated Camera"),
            camera("cam-obs", "OBS Virtual Camera"),
            microphone("mic-1", "Microphone (Realtek)"),
        ],
    );
    assert_eq!(seen.len(), 1, "{seen:?}");
    let Observation::VirtualDevice(found) = &seen[0] else {
        panic!("{seen:?}")
    };
    assert!(found.at_start);
    assert_eq!(found.device.id, "cam-obs");
    assert_eq!(found.matched, "OBS Virtual Camera");
}

#[test]
fn device_changes_carry_what_remains_and_new_virtual_devices_are_flagged() {
    let mut tracker = DeviceTracker::new(VirtualDeviceCatalogue::default());
    let cam = camera("cam-1", "Integrated Camera");
    let mic = microphone("mic-1", "Microphone (Realtek)");
    tracker.update(1, vec![cam.clone(), mic.clone()]);

    let seen = tracker.update(2, vec![mic.clone()]);
    assert_eq!(seen.len(), 1);
    let Observation::DeviceChanged(change) = &seen[0] else {
        panic!("{seen:?}")
    };
    assert_eq!(change.change, DeviceChangeKind::Disconnected);
    assert_eq!(change.device, cam);
    assert_eq!(change.remaining, 0);

    let cable = microphone("mic-vb", "CABLE Output (VB-Audio Virtual Cable)");
    let seen = tracker.update(3, vec![mic.clone(), cable.clone(), cam.clone()]);
    let kinds: Vec<_> = seen
        .iter()
        .map(|o| match o {
            Observation::DeviceChanged(c) => format!("{:?} {}", c.change, c.device.id),
            Observation::VirtualDevice(v) => format!("virtual {}", v.device.id),
            other => panic!("{other:?}"),
        })
        .collect();
    assert_eq!(
        kinds,
        ["Connected cam-1", "Connected mic-vb", "virtual mic-vb"],
        "{seen:?}"
    );
}

fn entry(pid: u32, parent: u32, name: &str) -> ProcessEntry {
    ProcessEntry {
        pid,
        parent_pid: parent,
        name: name.to_owned(),
    }
}

fn enrich(entry: &ProcessEntry, titles: Vec<String>, interview: bool) -> ProcessInfo {
    ProcessInfo {
        pid: entry.pid,
        parent_pid: entry.parent_pid,
        name: entry.name.clone(),
        path: Some(format!(r"C:\Apps\{}", entry.name)),
        start_time_ms: None,
        window_titles: titles,
        sha256: None,
        signature: SignatureInfo::default(),
        interview_app: interview,
    }
}

#[test]
fn the_interview_tree_holds_the_app_and_its_descendants() {
    let entries = [
        entry(4, 0, "System"),
        entry(100, 4, "explorer.exe"),
        entry(200, 100, "AI-Interview.exe"),
        entry(300, 200, "msedgewebview2.exe"),
        entry(301, 300, "msedgewebview2.exe"),
        entry(400, 100, "chrome.exe"),
    ];
    let tree = interview_tree(&entries, 200);
    let mut pids: Vec<_> = tree.into_iter().collect();
    pids.sort_unstable();
    assert_eq!(pids, [200, 300, 301]);
}

#[test]
fn processes_start_exit_and_change_titles() {
    let mut tracker = ProcessTracker::default();
    let mut titles: HashMap<u32, Vec<String>> = HashMap::new();
    titles.insert(10, vec!["Inbox".to_owned()]);
    let first = tracker.update(
        1,
        &[entry(10, 1, "mail.exe"), entry(11, 1, "svc.exe")],
        &titles,
        200,
        enrich,
    );
    assert_eq!(first.len(), 2);
    assert!(
        first
            .iter()
            .all(|o| matches!(o, Observation::ProcessStarted { at_start: true, .. }))
    );

    titles.insert(10, vec!["Inbox".to_owned(), "Compose".to_owned()]);
    let second = tracker.update(
        2,
        &[entry(10, 1, "mail.exe"), entry(12, 1, "anydesk.exe")],
        &titles,
        200,
        enrich,
    );
    let summary: Vec<_> = second
        .iter()
        .map(|o| match o {
            Observation::ProcessStarted {
                at_start, process, ..
            } => format!("started {} {at_start}", process.pid),
            Observation::ProcessExited { pid, name, .. } => format!("exited {pid} {name}"),
            Observation::ProcessWindowsChanged {
                pid, window_titles, ..
            } => format!("titles {pid} {}", window_titles.join("|")),
            other => panic!("{other:?}"),
        })
        .collect();
    assert_eq!(
        summary,
        [
            "exited 11 svc.exe",
            "started 12 false",
            "titles 10 Inbox|Compose"
        ]
    );
}

#[test]
fn a_reused_pid_with_another_name_is_a_new_process() {
    let mut tracker = ProcessTracker::default();
    let titles = HashMap::new();
    tracker.update(1, &[entry(10, 1, "notepad.exe")], &titles, 0, enrich);
    let seen = tracker.update(2, &[entry(10, 1, "anydesk.exe")], &titles, 0, enrich);
    assert!(
        matches!(&seen[0], Observation::ProcessExited { pid: 10, name, .. } if name == "notepad.exe")
    );
    assert!(
        matches!(&seen[1], Observation::ProcessStarted { process, .. } if process.name == "anydesk.exe")
    );
}

#[test]
fn processes_in_the_interview_tree_are_marked() {
    let mut tracker = ProcessTracker::default();
    let seen = tracker.update(
        1,
        &[
            entry(200, 1, "AI-Interview.exe"),
            entry(300, 200, "msedgewebview2.exe"),
        ],
        &HashMap::new(),
        200,
        enrich,
    );
    assert!(seen.iter().all(|o| matches!(
        o,
        Observation::ProcessStarted { process, .. } if process.interview_app
    )));
}

fn window(hwnd: isize, pid: u32, affinity: u32) -> WindowFacts {
    WindowFacts {
        hwnd,
        pid,
        process_name: "helper.exe".to_owned(),
        title: "Helper".to_owned(),
        visible: true,
        cloaked: false,
        display_affinity: affinity,
        topmost: false,
        layered: false,
        width: 400,
        height: 300,
    }
}

#[test]
fn capture_excluded_windows_of_other_processes_are_reported_once() {
    let mut tracker = WindowTracker::default();
    let interview = [200].into_iter().collect();
    let windows = vec![
        window(1, 50, 0x11),
        window(2, 200, 0x11), // the interview app's own window
        window(3, 51, 0x1),   // monitor-only affinity
        window(4, 52, 0),
        WindowFacts {
            visible: false,
            ..window(5, 53, 0x11)
        },
    ];
    let seen = tracker.update(1, &windows, &interview);
    let hits: Vec<_> = seen
        .iter()
        .map(|o| match o {
            Observation::CaptureExcludedWindow(w) => (w.pid, w.display_affinity),
            other => panic!("{other:?}"),
        })
        .collect();
    assert_eq!(hits, [(50, 0x11), (51, 0x1)]);
    assert_eq!(seen[0].contract_event(), Some("CAPTURE_EXCLUDED_WINDOW"));
    assert!(tracker.update(2, &windows, &interview).is_empty());

    // Gone, then back: reported again.
    tracker.update(3, &[], &interview);
    assert_eq!(tracker.update(4, &windows, &interview).len(), 2);
}

#[test]
fn topmost_layered_windows_of_other_processes_are_overlays() {
    let mut tracker = WindowTracker::default();
    let interview = std::collections::HashSet::new();
    let overlay = WindowFacts {
        topmost: true,
        layered: true,
        ..window(9, 60, 0)
    };
    let tiny = WindowFacts {
        width: 20,
        height: 20,
        ..overlay.clone()
    };
    let cloaked = WindowFacts {
        hwnd: 10,
        cloaked: true,
        ..overlay.clone()
    };
    let seen = tracker.update(1, &[overlay, tiny, cloaked], &interview);
    assert_eq!(seen.len(), 1, "{seen:?}");
    assert!(matches!(&seen[0], Observation::OverlayWindow(w) if w.pid == 60));
    assert_eq!(seen[0].contract_event(), None);
}

#[test]
fn a_remote_session_is_reported_when_it_starts() {
    let mut tracker = RemoteTracker::default();
    assert!(tracker.update(1, false, false).is_empty());
    let seen = tracker.update(2, true, false);
    assert!(
        matches!(&seen[..], [Observation::RemoteSession(r)] if r.remote_session && r.at_ms == 2)
    );
    assert!(tracker.update(3, true, false).is_empty());
    assert_eq!(tracker.update(4, true, true).len(), 1);
    assert!(tracker.update(5, false, false).is_empty());
}
