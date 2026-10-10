//! On-device rules: observations to contract events.

use hv_event_queue::{AppRules, DeviceRules, EventDraft, EventName, PolicyMatcher, Thresholds};
use hv_monitor::{
    AppRef, CaptureDevice, DeviceChange, DeviceChangeKind, DeviceKind, DisplayChange,
    DisplayChangeKind, DisplayInfo, FocusChange, IntegrityFinding, MinimizeChange, Observation,
    ProcessInfo, RemoteSession, SignatureInfo, VirtualDeviceFound, VirtualMachine, WindowSighting,
};
use serde_json::json;

fn rules_with(app_rules: serde_json::Value, single_display: bool) -> DeviceRules {
    let app_rules: AppRules = serde_json::from_value(app_rules).expect("rules");
    DeviceRules::new(
        PolicyMatcher::new(&app_rules),
        Thresholds::default(),
        single_display,
    )
}

fn rules() -> DeviceRules {
    rules_with(json!({}), false)
}

fn app(pid: u32, name: &str, interview: bool) -> AppRef {
    AppRef {
        pid,
        name: name.to_owned(),
        window_title: format!("{name} window"),
        interview_app: interview,
    }
}

fn focus(at_ms: i64, previous: Option<AppRef>, new: AppRef) -> Observation {
    Observation::FocusChanged(FocusChange {
        at_ms,
        previous,
        new,
        previous_duration_ms: None,
    })
}

fn names(drafts: &[EventDraft]) -> Vec<EventName> {
    drafts.iter().map(|d| d.event).collect()
}

#[test]
fn a_short_trip_away_from_the_interview_is_not_reported() {
    let mut rules = rules();
    let interview = app(1, "AI-Interview.exe", true);
    let chrome = app(2, "chrome.exe", false);
    assert!(
        rules
            .observe(&focus(1_000, Some(interview.clone()), chrome.clone()))
            .is_empty()
    );
    assert!(rules.tick(3_500).is_empty());
    assert!(
        rules
            .observe(&focus(3_900, Some(chrome), interview))
            .is_empty(),
        "2.9 s is under the 3 s threshold"
    );
}

#[test]
fn focus_away_for_more_than_three_seconds_is_reported_with_its_duration() {
    let mut rules = rules();
    let interview = app(1, "AI-Interview.exe", true);
    let chrome = app(2, "chrome.exe", false);
    let notepad = app(3, "notepad.exe", false);
    rules.observe(&focus(1_000, Some(interview.clone()), chrome.clone()));
    rules.observe(&focus(2_000, Some(chrome), notepad.clone()));
    let drafts = rules.observe(&focus(5_400, Some(notepad), interview));
    assert_eq!(names(&drafts), [EventName::ApplicationFocusChange]);
    let draft = &drafts[0];
    assert_eq!(draft.started_at_ms, 1_000);
    assert_eq!(draft.duration_ms, Some(4_400));
    assert_eq!(draft.details["previous_app"], "AI-Interview.exe");
    assert_eq!(draft.details["new_app"], "chrome.exe");
    assert_eq!(draft.details["window_title"], "chrome.exe window");
    assert_eq!(draft.details["apps"], json!(["chrome.exe", "notepad.exe"]));
    assert_eq!(draft.details["ongoing"], false);
}

#[test]
fn a_long_absence_is_reported_in_chunks_while_it_lasts() {
    let mut rules = rules();
    let interview = app(1, "AI-Interview.exe", true);
    let chrome = app(2, "chrome.exe", false);
    rules.observe(&focus(0, Some(interview.clone()), chrome.clone()));
    assert!(rules.tick(9_999).is_empty());
    let first = rules.tick(10_000);
    assert_eq!(names(&first), [EventName::ApplicationFocusChange]);
    assert_eq!(
        (first[0].started_at_ms, first[0].duration_ms),
        (0, Some(10_000))
    );
    assert_eq!(first[0].details["ongoing"], true);
    let last = rules.observe(&focus(12_500, Some(chrome), interview));
    assert_eq!(
        (last[0].started_at_ms, last[0].duration_ms),
        (10_000, Some(2_500))
    );
    assert_eq!(last[0].details["continued"], true);
    assert_eq!(last[0].details["ongoing"], false);
}

#[test]
fn stopping_closes_an_open_absence() {
    let mut rules = rules();
    rules.observe(&focus(
        0,
        Some(app(1, "AI-Interview.exe", true)),
        app(2, "chrome.exe", false),
    ));
    let drafts = rules.finish(4_000);
    assert_eq!(names(&drafts), [EventName::ApplicationFocusChange]);
    assert_eq!(drafts[0].duration_ms, Some(4_000));
    assert!(rules.finish(9_000).is_empty());
}

#[test]
fn thresholds_come_from_the_policy() {
    let mut rules = DeviceRules::new(
        PolicyMatcher::new(&AppRules::default()),
        Thresholds {
            focus_away_ms: 10_000,
            ..Thresholds::default()
        },
        false,
    );
    let interview = app(1, "AI-Interview.exe", true);
    let chrome = app(2, "chrome.exe", false);
    rules.observe(&focus(0, Some(interview.clone()), chrome.clone()));
    assert!(
        rules
            .observe(&focus(6_000, Some(chrome), interview))
            .is_empty()
    );
}

#[test]
fn minimising_the_interview_app_for_more_than_three_seconds_is_reported() {
    let mut rules = rules();
    let interview = app(1, "AI-Interview.exe", true);
    let minimise = |at_ms, app: &AppRef, minimized| {
        Observation::Minimize(MinimizeChange {
            at_ms,
            app: app.clone(),
            minimized,
        })
    };
    // Other apps minimising don't matter.
    assert!(
        rules
            .observe(&minimise(0, &app(2, "chrome.exe", false), true))
            .is_empty()
    );
    rules.observe(&minimise(1_000, &interview, true));
    let drafts = rules.observe(&minimise(5_000, &interview, false));
    assert_eq!(names(&drafts), [EventName::WindowMinimized]);
    assert_eq!(drafts[0].duration_ms, Some(4_000));
    assert_eq!(drafts[0].details["app"], "AI-Interview.exe");
}

fn process(pid: u32, name: &str, sha256: &str) -> ProcessInfo {
    ProcessInfo {
        pid,
        parent_pid: 1,
        name: name.to_owned(),
        path: Some(format!(r"C:\Tools\{name}")),
        start_time_ms: Some(1_791_781_262_120),
        window_titles: vec![],
        sha256: Some(sha256.to_owned()),
        signature: SignatureInfo::default(),
        interview_app: false,
    }
}

#[test]
fn a_blocked_process_is_reported_once_with_its_metadata() {
    let mut rules = rules_with(
        json!({ "blocked": [ { "match": "hash", "value": "abc123", "category": "remote_access" } ] }),
        false,
    );
    let started = Observation::ProcessStarted {
        at_ms: 50,
        at_start: false,
        process: process(77, "renamed.exe", "ABC123"),
    };
    let drafts = rules.observe(&started);
    assert_eq!(names(&drafts), [EventName::BlockedProcessDetected]);
    let details = &drafts[0].details;
    assert_eq!(details["pid"], 77);
    assert_eq!(details["name"], "renamed.exe");
    assert_eq!(details["path"], r"C:\Tools\renamed.exe");
    assert_eq!(details["sha256"], "ABC123");
    assert_eq!(details["matched_by"], "hash");
    assert_eq!(details["category"], "remote_access");
    assert_eq!(details["severity_hint"], "critical");
    assert_eq!(details["already_running"], false);
    assert_eq!(details["start_time"], "2026-10-12T05:01:02.120Z");
    assert_eq!(drafts[0].started_at_ms, 50);
    assert!(rules.observe(&started).is_empty(), "once per process");
    assert!(
        rules
            .observe(&Observation::ProcessStarted {
                at_ms: 60,
                at_start: false,
                process: process(78, "fine.exe", "ffff"),
            })
            .is_empty()
    );
}

#[test]
fn a_window_title_rule_fires_when_the_title_appears() {
    let mut rules = rules_with(
        json!({ "blocked": [ { "match": "window_title", "value": "ChatGPT" } ] }),
        false,
    );
    assert!(
        rules
            .observe(&Observation::ProcessStarted {
                at_ms: 1,
                at_start: true,
                process: process(5, "browser.exe", "00"),
            })
            .is_empty()
    );
    let drafts = rules.observe(&Observation::ProcessWindowsChanged {
        at_ms: 2,
        pid: 5,
        window_titles: vec!["ChatGPT - Browser".to_owned()],
    });
    assert_eq!(names(&drafts), [EventName::BlockedProcessDetected]);
    assert_eq!(drafts[0].details["severity_hint"], "warning");
    assert_eq!(
        drafts[0].details["window_titles"],
        json!(["ChatGPT - Browser"])
    );
}

fn display(name: &str) -> DisplayInfo {
    DisplayInfo {
        name: name.to_owned(),
        x: 0,
        y: 0,
        width: 1920,
        height: 1080,
        primary: false,
    }
}

#[test]
fn plugging_in_a_second_monitor_is_an_external_display_change() {
    let change = Observation::DisplayChanged(DisplayChange {
        at_ms: 10,
        change: DisplayChangeKind::Connected,
        display: display(r"\\.\DISPLAY2"),
        previous: None,
        display_count: 2,
        previous_count: 1,
    });
    let drafts = rules().observe(&change);
    assert_eq!(names(&drafts), [EventName::ExternalDisplayChange]);
    assert_eq!(drafts[0].details["change"], "connected");
    assert_eq!(drafts[0].details["display_count"], 2);
    assert_eq!(drafts[0].details["severity_hint"], "warning");
    let strict = rules_with(json!({}), true).observe(&change);
    assert_eq!(strict[0].details["severity_hint"], "critical");
}

fn device(kind: DeviceKind, id: &str, name: &str) -> CaptureDevice {
    CaptureDevice {
        kind,
        id: id.to_owned(),
        name: name.to_owned(),
    }
}

fn device_change(at_ms: i64, change: DeviceChangeKind, device: CaptureDevice) -> Observation {
    Observation::DeviceChanged(DeviceChange {
        at_ms,
        change,
        device,
        remaining: 0,
    })
}

#[test]
fn the_active_camera_disconnecting_and_reconnecting_is_reported() {
    let mut rules = rules();
    rules.set_active_devices(Some("Integrated Camera".to_owned()), None);
    let cam = device(DeviceKind::Camera, "cam-1", "Integrated Camera");
    let other = device(DeviceKind::Camera, "cam-2", "USB Camera");
    assert!(
        rules
            .observe(&device_change(1, DeviceChangeKind::Disconnected, other))
            .is_empty(),
        "not the camera in use"
    );
    let gone = rules.observe(&device_change(
        2,
        DeviceChangeKind::Disconnected,
        cam.clone(),
    ));
    assert_eq!(names(&gone), [EventName::CameraDisconnected]);
    let back = rules.observe(&device_change(3, DeviceChangeKind::Connected, cam));
    assert_eq!(names(&back), [EventName::CameraReconnected]);
}

#[test]
fn without_an_active_device_any_microphone_disconnect_is_reported() {
    let mut rules = rules();
    let mic = device(DeviceKind::Microphone, "mic-1", "Microphone (Realtek)");
    let new = device(DeviceKind::Microphone, "mic-9", "Headset");
    assert!(
        rules
            .observe(&device_change(1, DeviceChangeKind::Connected, new))
            .is_empty(),
        "a new device isn't a reconnection"
    );
    let gone = rules.observe(&device_change(
        2,
        DeviceChangeKind::Disconnected,
        mic.clone(),
    ));
    assert_eq!(names(&gone), [EventName::MicDisconnected]);
    assert_eq!(gone[0].details["active"], serde_json::Value::Null);
    let back = rules.observe(&device_change(3, DeviceChangeKind::Connected, mic));
    assert_eq!(names(&back), [EventName::MicReconnected]);
}

#[test]
fn environment_observations_map_to_their_events() {
    let mut rules = rules();
    let sighting = WindowSighting {
        at_ms: 5,
        pid: 44,
        process_name: "overlay.exe".to_owned(),
        window_title: "Helper".to_owned(),
        display_affinity: 0x11,
        width: 300,
        height: 200,
    };
    let cases = [
        (
            Observation::CaptureExcludedWindow(sighting.clone()),
            Some(EventName::CaptureExcludedWindow),
        ),
        (Observation::OverlayWindow(sighting), None),
        (
            Observation::RemoteSession(RemoteSession {
                at_ms: 6,
                remote_session: true,
                remote_control: false,
            }),
            Some(EventName::RemoteSessionDetected),
        ),
        (
            Observation::VirtualMachine(VirtualMachine {
                at_ms: 7,
                hypervisor_present: true,
                vendor: Some("VMwareVMware".to_owned()),
            }),
            Some(EventName::VmDetected),
        ),
        (
            Observation::ClientIntegrity(IntegrityFinding {
                at_ms: 8,
                reason: "debugger_attached".to_owned(),
                detail: None,
            }),
            Some(EventName::ClientIntegrityWarning),
        ),
        (
            Observation::VirtualDevice(VirtualDeviceFound {
                at_ms: 9,
                device: device(DeviceKind::Camera, "obs", "OBS Virtual Camera"),
                matched: "OBS Virtual Camera".to_owned(),
                at_start: true,
            }),
            Some(EventName::VirtualDeviceDetected),
        ),
    ];
    for (observation, expected) in cases {
        let drafts = rules.observe(&observation);
        assert_eq!(drafts.first().map(|d| d.event), expected, "{observation:?}");
        if let Some(draft) = drafts.first() {
            assert_eq!(draft.started_at_ms, observation.at_ms());
            assert_eq!(draft.source, hv_event_queue::Source::Native);
        }
    }
    let excluded = rules.observe(&Observation::CaptureExcludedWindow(WindowSighting {
        at_ms: 10,
        pid: 45,
        process_name: "x.exe".to_owned(),
        window_title: String::new(),
        display_affinity: 0x11,
        width: 1,
        height: 1,
    }));
    assert_eq!(
        excluded[0].details["display_affinity"],
        "exclude_from_capture"
    );
}
