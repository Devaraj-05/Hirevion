//! The device's share of the §6.12 rules: which observations become contract events, and the
//! temporal thresholds that belong on the device (focus and minimise > 3 s).

use std::collections::{HashMap, HashSet};

use hv_monitor::{
    AppRef, DeviceChangeKind, DeviceKind, DisplayChangeKind, Observation, ProcessInfo,
    SignatureStatus,
};
use serde_json::{Value, json};

use crate::event::{EventDraft, EventName, Source, rfc3339_ms};
use crate::policy::{PolicyMatcher, SessionPolicy, SeverityHint};

/// Temporal thresholds, from the session policy's `thresholds` (`warn_after_ms`), defaulting to
/// the §6.12 table.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Thresholds {
    /// `APPLICATION_FOCUS_CHANGE` is reported once the interview app has lost focus for longer.
    pub focus_away_ms: u64,
    /// `WINDOW_MINIMIZED` is reported once the interview app has been minimised for longer.
    pub minimized_ms: u64,
    /// A period still going on is reported in chunks of this length, so the server hears of
    /// it while it lasts; the chunks are back to back and their durations add up.
    pub split_after_ms: u64,
}

impl Default for Thresholds {
    fn default() -> Self {
        Self {
            focus_away_ms: 3_000,
            minimized_ms: 3_000,
            split_after_ms: 10_000,
        }
    }
}

impl Thresholds {
    pub fn from_policy(policy: &SessionPolicy) -> Self {
        let defaults = Self::default();
        let warn = |event: EventName, default: u64| {
            policy
                .thresholds
                .get(event.as_str())
                .and_then(|t| t.warn_after_ms)
                .unwrap_or(default)
        };
        Self {
            focus_away_ms: warn(EventName::ApplicationFocusChange, defaults.focus_away_ms),
            minimized_ms: warn(EventName::WindowMinimized, defaults.minimized_ms),
            split_after_ms: defaults.split_after_ms,
        }
    }
}

/// An open period (focus away, minimised).
#[derive(Debug, Clone)]
struct Period {
    since: i64,
    chunk_start: i64,
    /// The app focus went to first (focus) or the minimised app (minimise).
    first: AppRef,
    /// Every app that held focus during the period, in order.
    apps: Vec<String>,
}

/// Apps listed per absence, at most.
const APPS_LISTED: usize = 20;

/// Turns monitor observations into event drafts.
#[derive(Debug)]
pub struct DeviceRules {
    matcher: PolicyMatcher,
    thresholds: Thresholds,
    single_display: bool,
    interview_name: String,
    away: Option<Period>,
    minimized: Option<Period>,
    processes: HashMap<u32, (ProcessInfo, bool)>,
    blocked_reported: HashSet<u32>,
    active: HashMap<DeviceKind, String>,
    disconnected: HashSet<(DeviceKind, String)>,
}

impl DeviceRules {
    pub fn new(matcher: PolicyMatcher, thresholds: Thresholds, single_display: bool) -> Self {
        let interview_name = std::env::current_exe()
            .ok()
            .and_then(|p| p.file_name().map(|n| n.to_string_lossy().into_owned()))
            .unwrap_or_else(|| "interview_app".to_owned());
        Self {
            matcher,
            thresholds,
            single_display,
            interview_name,
            away: None,
            minimized: None,
            processes: HashMap::new(),
            blocked_reported: HashSet::new(),
            active: HashMap::new(),
            disconnected: HashSet::new(),
        }
    }

    /// Rules for a proctor session: its app rules, thresholds and display policy.
    pub fn from_policy(policy: &SessionPolicy) -> Self {
        Self::new(
            PolicyMatcher::new(&policy.app_rules),
            Thresholds::from_policy(policy),
            policy.single_display,
        )
    }

    /// The camera and microphone the interview uses (their device names, as the webview's
    /// `MediaDeviceInfo.label` shows them). With one set, only that device's disconnects count;
    /// without, any device of that kind does.
    pub fn set_active_devices(&mut self, camera: Option<String>, microphone: Option<String>) {
        for (kind, name) in [
            (DeviceKind::Camera, camera),
            (DeviceKind::Microphone, microphone),
        ] {
            match name {
                Some(name) => self.active.insert(kind, name.to_lowercase()),
                None => self.active.remove(&kind),
            };
        }
    }

    /// The drafts one observation produces.
    pub fn observe(&mut self, observation: &Observation) -> Vec<EventDraft> {
        match observation {
            Observation::ProcessStarted {
                at_ms,
                at_start,
                process,
            } => {
                self.processes
                    .insert(process.pid, (process.clone(), *at_start));
                self.check_process(process.pid, *at_ms)
                    .into_iter()
                    .collect()
            }
            Observation::ProcessWindowsChanged {
                at_ms,
                pid,
                window_titles,
            } => {
                if let Some((process, _)) = self.processes.get_mut(pid) {
                    process.window_titles.clone_from(window_titles);
                }
                self.check_process(*pid, *at_ms).into_iter().collect()
            }
            Observation::ProcessExited { pid, .. } => {
                self.processes.remove(pid);
                self.blocked_reported.remove(pid);
                Vec::new()
            }
            Observation::FocusChanged(change) => {
                self.focus(change.at_ms, change.previous.as_ref(), &change.new)
            }
            Observation::Minimize(change) => {
                self.minimize(change.at_ms, &change.app, change.minimized)
            }
            Observation::DisplayChanged(change) => {
                let critical = self.single_display && change.display_count > 1;
                vec![
                    native(EventName::ExternalDisplayChange, change.at_ms).details(json!({
                        "change": display_change(change.change),
                        "display": change.display,
                        "previous": change.previous,
                        "display_count": change.display_count,
                        "previous_count": change.previous_count,
                        "single_display": self.single_display,
                        "severity_hint": if critical { SeverityHint::Critical } else { SeverityHint::Warning },
                    })),
                ]
            }
            Observation::DeviceChanged(change) => {
                let key = (change.device.kind, change.device.id.clone());
                let active = self.active.get(&change.device.kind);
                let is_active = active.map(|name| *name == change.device.name.to_lowercase());
                let (gone, back) = match change.device.kind {
                    DeviceKind::Camera => {
                        (EventName::CameraDisconnected, EventName::CameraReconnected)
                    }
                    DeviceKind::Microphone => {
                        (EventName::MicDisconnected, EventName::MicReconnected)
                    }
                };
                let event = match change.change {
                    DeviceChangeKind::Disconnected if is_active != Some(false) => {
                        self.disconnected.insert(key);
                        Some(gone)
                    }
                    DeviceChangeKind::Connected if self.disconnected.remove(&key) => Some(back),
                    // Other devices coming and going: a proposed DEVICE_CHANGE event.
                    _ => None,
                };
                event
                    .map(|event| {
                        native(event, change.at_ms).details(json!({
                            "device_name": change.device.name,
                            "device_id": change.device.id,
                            "remaining": change.remaining,
                            "active": is_active,
                        }))
                    })
                    .into_iter()
                    .collect()
            }
            Observation::VirtualDevice(found) => vec![
                native(EventName::VirtualDeviceDetected, found.at_ms).details(json!({
                    "kind": found.device.kind,
                    "device_name": found.device.name,
                    "device_id": found.device.id,
                    "matched": found.matched,
                    "present_at_start": found.at_start,
                })),
            ],
            Observation::CaptureExcludedWindow(window) => vec![
                native(EventName::CaptureExcludedWindow, window.at_ms).details(json!({
                    "pid": window.pid,
                    "process_name": window.process_name,
                    "window_title": window.window_title,
                    "display_affinity": affinity(window.display_affinity),
                    "width": window.width,
                    "height": window.height,
                })),
            ],
            // §62 "unexpected window": no contract event yet (proposed UNEXPECTED_WINDOW).
            Observation::OverlayWindow(_) => Vec::new(),
            Observation::RemoteSession(remote) => vec![
                native(EventName::RemoteSessionDetected, remote.at_ms).details(json!({
                    "remote_session": remote.remote_session,
                    "remote_control": remote.remote_control,
                })),
            ],
            Observation::VirtualMachine(vm) => {
                vec![native(EventName::VmDetected, vm.at_ms).details(json!({
                    "hypervisor_present": vm.hypervisor_present,
                    "vendor": vm.vendor,
                }))]
            }
            Observation::ClientIntegrity(finding) => vec![
                native(EventName::ClientIntegrityWarning, finding.at_ms).details(json!({
                    "reason": finding.reason,
                    "detail": finding.detail,
                })),
            ],
        }
    }

    /// Chunks of periods still open at `now_ms`. Call it about once a second.
    pub fn tick(&mut self, now_ms: i64) -> Vec<EventDraft> {
        let split = i64::try_from(self.thresholds.split_after_ms).unwrap_or(i64::MAX);
        let mut drafts = Vec::new();
        let interview_name = self.interview_name.clone();
        if let Some(away) = &mut self.away
            && now_ms - away.chunk_start >= split
        {
            drafts.push(away_draft(away, &interview_name, now_ms, true));
            away.chunk_start = now_ms;
        }
        if let Some(minimized) = &mut self.minimized
            && now_ms - minimized.chunk_start >= split
        {
            drafts.push(minimized_draft(minimized, now_ms, true));
            minimized.chunk_start = now_ms;
        }
        drafts
    }

    /// Closes the open periods (the interview ends or monitoring stops).
    pub fn finish(&mut self, now_ms: i64) -> Vec<EventDraft> {
        let mut drafts = Vec::new();
        if let Some(away) = self.away.take() {
            drafts.extend(self.close_away(&away, now_ms));
        }
        if let Some(minimized) = self.minimized.take()
            && exceeds(&minimized, now_ms, self.thresholds.minimized_ms)
        {
            drafts.push(minimized_draft(&minimized, now_ms, false));
        }
        drafts
    }

    fn focus(&mut self, at_ms: i64, previous: Option<&AppRef>, new: &AppRef) -> Vec<EventDraft> {
        if let Some(previous) = previous.filter(|p| p.interview_app) {
            self.interview_name.clone_from(&previous.name);
        }
        if new.interview_app {
            self.interview_name.clone_from(&new.name);
            return match self.away.take() {
                Some(away) => self.close_away(&away, at_ms).into_iter().collect(),
                None => Vec::new(),
            };
        }
        match &mut self.away {
            Some(away) => {
                if away.apps.len() < APPS_LISTED && away.apps.last() != Some(&new.name) {
                    away.apps.push(new.name.clone());
                }
            }
            None => {
                self.away = Some(Period {
                    since: at_ms,
                    chunk_start: at_ms,
                    first: new.clone(),
                    apps: vec![new.name.clone()],
                });
            }
        }
        Vec::new()
    }

    fn close_away(&self, away: &Period, at_ms: i64) -> Option<EventDraft> {
        exceeds(away, at_ms, self.thresholds.focus_away_ms)
            .then(|| away_draft(away, &self.interview_name, at_ms, false))
    }

    fn minimize(&mut self, at_ms: i64, app: &AppRef, minimized: bool) -> Vec<EventDraft> {
        if !app.interview_app {
            return Vec::new();
        }
        if minimized {
            if self.minimized.is_none() {
                self.minimized = Some(Period {
                    since: at_ms,
                    chunk_start: at_ms,
                    first: app.clone(),
                    apps: Vec::new(),
                });
            }
            return Vec::new();
        }
        match self.minimized.take() {
            Some(period) if exceeds(&period, at_ms, self.thresholds.minimized_ms) => {
                vec![minimized_draft(&period, at_ms, false)]
            }
            _ => Vec::new(),
        }
    }

    fn check_process(&mut self, pid: u32, at_ms: i64) -> Option<EventDraft> {
        if self.blocked_reported.contains(&pid) {
            return None;
        }
        let (process, at_start) = self.processes.get(&pid)?;
        let hit = self.matcher.evaluate(process)?;
        self.blocked_reported.insert(pid);
        Some(
            native(EventName::BlockedProcessDetected, at_ms).details(json!({
                "pid": process.pid,
                "parent_pid": process.parent_pid,
                "name": process.name,
                "path": process.path,
                "publisher": process.signature.signer,
                "signature_status": signature_status(process.signature.status),
                "signer_cert_sha256": process.signature.signer_cert_sha256,
                "sha256": process.sha256,
                "start_time": process.start_time_ms.map(rfc3339_ms),
                "window_titles": process.window_titles,
                "matched_by": hit.matched_by.as_str(),
                "rule_index": hit.rule_index,
                "category": hit.category,
                "severity_hint": hit.severity_hint,
                "already_running": at_start,
            })),
        )
    }
}

/// Whether a period that ends at `at_ms` lasted longer than `threshold_ms` in all.
fn exceeds(period: &Period, at_ms: i64, threshold_ms: u64) -> bool {
    u64::try_from(at_ms - period.since).is_ok_and(|total| total > threshold_ms)
}

fn chunk(period: &Period, at_ms: i64) -> u64 {
    u64::try_from(at_ms - period.chunk_start).unwrap_or(0)
}

fn away_draft(away: &Period, interview_name: &str, at_ms: i64, ongoing: bool) -> EventDraft {
    native(EventName::ApplicationFocusChange, away.chunk_start)
        .duration_ms(chunk(away, at_ms))
        .details(json!({
            "previous_app": interview_name,
            "new_app": away.first.name,
            "window_title": away.first.window_title,
            "apps": away.apps,
            "ongoing": ongoing,
            "continued": away.chunk_start != away.since,
        }))
}

fn minimized_draft(period: &Period, at_ms: i64, ongoing: bool) -> EventDraft {
    native(EventName::WindowMinimized, period.chunk_start)
        .duration_ms(chunk(period, at_ms))
        .details(json!({
            "app": period.first.name,
            "window_title": period.first.window_title,
            "ongoing": ongoing,
            "continued": period.chunk_start != period.since,
        }))
}

fn native(event: EventName, at_ms: i64) -> EventDraft {
    EventDraft::new(event, Source::Native, at_ms)
}

fn display_change(kind: DisplayChangeKind) -> &'static str {
    match kind {
        DisplayChangeKind::Connected => "connected",
        DisplayChangeKind::Disconnected => "disconnected",
        DisplayChangeKind::Reconfigured => "reconfigured",
        DisplayChangeKind::PresentAtStart => "present_at_start",
    }
}

fn signature_status(status: SignatureStatus) -> &'static str {
    match status {
        SignatureStatus::Valid => "valid",
        SignatureStatus::Unsigned => "unsigned",
        SignatureStatus::Invalid => "invalid",
        SignatureStatus::Unknown => "unknown",
    }
}

fn affinity(value: u32) -> Value {
    match value {
        0x11 => json!("exclude_from_capture"),
        0x1 => json!("monitor"),
        other => json!(other),
    }
}
