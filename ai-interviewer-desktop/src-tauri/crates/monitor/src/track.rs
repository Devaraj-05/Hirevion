//! Pure trackers: each keeps the previous scan and turns the next one into observations.
//!
//! The Win32 scanning lives in `native`; everything that decides what changed lives here, so it
//! is tested with fakes.

use std::collections::{BTreeMap, HashMap, HashSet};

use crate::observation::{
    CaptureDevice, DeviceChange, DeviceChangeKind, DisplayChange, DisplayChangeKind, DisplayInfo,
    Observation, ProcessInfo, RemoteSession, VirtualDeviceFound, WindowSighting,
};
use crate::virtual_devices::VirtualDeviceCatalogue;

/// Displays: connects, disconnects and reconfigurations by GDI device name.
#[derive(Debug, Default)]
pub struct DisplayTracker {
    last: Option<Vec<DisplayInfo>>,
}

impl DisplayTracker {
    /// The observations for this scan. The first scan reports only when several displays
    /// are connected.
    pub fn update(&mut self, at_ms: i64, displays: Vec<DisplayInfo>) -> Vec<Observation> {
        let count = displays.len();
        let Some(before) = self.last.replace(displays.clone()) else {
            if count > 1 {
                // One observation per extra display would repeat itself; the first
                // non-primary one stands for the set, and `display_count` says how many.
                let extra = displays
                    .iter()
                    .find(|d| !d.primary)
                    .unwrap_or(&displays[0])
                    .clone();
                return vec![Observation::DisplayChanged(DisplayChange {
                    at_ms,
                    change: DisplayChangeKind::PresentAtStart,
                    display: extra,
                    previous: None,
                    display_count: count,
                    previous_count: 0,
                })];
            }
            return Vec::new();
        };
        let previous_count = before.len();
        let change = |change, display: &DisplayInfo, previous: Option<&DisplayInfo>| {
            Observation::DisplayChanged(DisplayChange {
                at_ms,
                change,
                display: display.clone(),
                previous: previous.cloned(),
                display_count: count,
                previous_count,
            })
        };
        let old: BTreeMap<&str, &DisplayInfo> =
            before.iter().map(|d| (d.name.as_str(), d)).collect();
        let new: BTreeMap<&str, &DisplayInfo> =
            displays.iter().map(|d| (d.name.as_str(), d)).collect();
        let mut seen = Vec::new();
        for (name, display) in &old {
            if !new.contains_key(name) {
                seen.push(change(DisplayChangeKind::Disconnected, display, None));
            }
        }
        for (name, display) in &new {
            match old.get(name) {
                None => seen.push(change(DisplayChangeKind::Connected, display, None)),
                Some(previous) if previous != display => seen.push(change(
                    DisplayChangeKind::Reconfigured,
                    display,
                    Some(previous),
                )),
                Some(_) => {}
            }
        }
        seen
    }
}

/// Cameras and microphones: connects and disconnects by device id, and virtual devices.
#[derive(Debug)]
pub struct DeviceTracker {
    catalogue: VirtualDeviceCatalogue,
    last: Option<Vec<CaptureDevice>>,
}

impl DeviceTracker {
    pub fn new(catalogue: VirtualDeviceCatalogue) -> Self {
        Self {
            catalogue,
            last: None,
        }
    }

    /// The observations for this scan. The first scan reports only virtual devices.
    pub fn update(&mut self, at_ms: i64, devices: Vec<CaptureDevice>) -> Vec<Observation> {
        let mut devices = devices;
        devices.sort_by(|a, b| (a.kind, &a.id).cmp(&(b.kind, &b.id)));
        devices.dedup_by(|a, b| a.kind == b.kind && a.id == b.id);
        let first = self.last.is_none();
        let before = self.last.replace(devices.clone()).unwrap_or_default();
        let key = |d: &CaptureDevice| (d.kind, d.id.clone());
        let old: HashSet<_> = before.iter().map(key).collect();
        let new: HashSet<_> = devices.iter().map(key).collect();
        let remaining =
            |device: &CaptureDevice| devices.iter().filter(|d| d.kind == device.kind).count();

        let mut seen = Vec::new();
        let mut added = Vec::new();
        for device in &before {
            if !new.contains(&key(device)) {
                seen.push(Observation::DeviceChanged(DeviceChange {
                    at_ms,
                    change: DeviceChangeKind::Disconnected,
                    device: device.clone(),
                    remaining: remaining(device),
                }));
            }
        }
        for device in &devices {
            if first {
                added.push(device);
            } else if !old.contains(&key(device)) {
                seen.push(Observation::DeviceChanged(DeviceChange {
                    at_ms,
                    change: DeviceChangeKind::Connected,
                    device: device.clone(),
                    remaining: remaining(device),
                }));
                added.push(device);
            }
        }
        for device in added {
            if let Some(matched) = self.catalogue.matches(&device.name) {
                seen.push(Observation::VirtualDevice(VirtualDeviceFound {
                    at_ms,
                    device: device.clone(),
                    matched: matched.to_owned(),
                    at_start: first,
                }));
            }
        }
        seen
    }
}

/// One row of the process list.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessEntry {
    pub pid: u32,
    pub parent_pid: u32,
    pub name: String,
}

/// The interview app's PID and every process descended from it (its WebView2 processes).
pub fn interview_tree(entries: &[ProcessEntry], interview_pid: u32) -> HashSet<u32> {
    let mut children: HashMap<u32, Vec<u32>> = HashMap::new();
    for entry in entries {
        // PID 0's parent is itself; never walk into a cycle.
        if entry.pid != entry.parent_pid {
            children
                .entry(entry.parent_pid)
                .or_default()
                .push(entry.pid);
        }
    }
    let mut tree = HashSet::new();
    if interview_pid == 0 {
        return tree;
    }
    let mut stack = vec![interview_pid];
    while let Some(pid) = stack.pop() {
        if tree.insert(pid) {
            stack.extend(children.get(&pid).into_iter().flatten().copied());
        }
    }
    tree
}

/// Processes: starts, exits and window-title changes between polls.
///
/// A process is keyed by PID and executable name, so a reused PID running another program is
/// a new process.
#[derive(Debug, Default)]
pub struct ProcessTracker {
    known: Option<BTreeMap<u32, (String, Vec<String>)>>,
}

impl ProcessTracker {
    /// The observations for this poll. `enrich` describes a newly seen process (path, hash,
    /// signature, start time); it gets the entry, its window titles and whether it belongs to
    /// the interview app.
    pub fn update(
        &mut self,
        at_ms: i64,
        entries: &[ProcessEntry],
        titles: &HashMap<u32, Vec<String>>,
        interview_pid: u32,
        mut enrich: impl FnMut(&ProcessEntry, Vec<String>, bool) -> ProcessInfo,
    ) -> Vec<Observation> {
        let at_start = self.known.is_none();
        let before = self.known.take().unwrap_or_default();
        let tree = interview_tree(entries, interview_pid);
        let mut after: BTreeMap<u32, (String, Vec<String>)> = BTreeMap::new();
        let mut exited = Vec::new();
        let mut started = Vec::new();
        let mut retitled = Vec::new();

        let mut sorted: Vec<&ProcessEntry> = entries.iter().collect();
        sorted.sort_by_key(|e| e.pid);
        sorted.dedup_by_key(|e| e.pid);
        for entry in &sorted {
            let window_titles = titles.get(&entry.pid).cloned().unwrap_or_default();
            match before.get(&entry.pid) {
                Some((name, old_titles)) if *name == entry.name => {
                    if *old_titles != window_titles {
                        retitled.push(Observation::ProcessWindowsChanged {
                            at_ms,
                            pid: entry.pid,
                            window_titles: window_titles.clone(),
                        });
                    }
                }
                _ => {
                    let process = enrich(entry, window_titles.clone(), tree.contains(&entry.pid));
                    started.push(Observation::ProcessStarted {
                        at_ms,
                        at_start,
                        process,
                    });
                }
            }
            after.insert(entry.pid, (entry.name.clone(), window_titles));
        }
        for (pid, (name, _)) in &before {
            if after.get(pid).is_none_or(|(now, _)| now != name) {
                exited.push(Observation::ProcessExited {
                    at_ms,
                    pid: *pid,
                    name: name.clone(),
                });
            }
        }
        self.known = Some(after);
        exited.into_iter().chain(started).chain(retitled).collect()
    }
}

/// What a scan learns about one top-level window.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowFacts {
    /// The `HWND` as an integer.
    pub hwnd: isize,
    pub pid: u32,
    pub process_name: String,
    pub title: String,
    pub visible: bool,
    /// Hidden by DWM (a suspended UWP app, another virtual desktop).
    pub cloaked: bool,
    pub display_affinity: u32,
    pub topmost: bool,
    pub layered: bool,
    pub width: u32,
    pub height: u32,
}

/// Overlays smaller than this on either side are ignored (tooltips, indicators).
const OVERLAY_MIN_SIDE: u32 = 100;

/// Windows hidden from capture, and overlays, each reported once while it exists.
#[derive(Debug, Default)]
pub struct WindowTracker {
    excluded: HashSet<(isize, u32)>,
    overlays: HashSet<isize>,
}

impl WindowTracker {
    /// The observations for this scan. Windows of `interview` processes are skipped.
    pub fn update(
        &mut self,
        at_ms: i64,
        windows: &[WindowFacts],
        interview: &HashSet<u32>,
    ) -> Vec<Observation> {
        let mut excluded = HashSet::new();
        let mut overlays = HashSet::new();
        let mut seen = Vec::new();
        let sighting = |w: &WindowFacts| WindowSighting {
            at_ms,
            pid: w.pid,
            process_name: w.process_name.clone(),
            window_title: w.title.clone(),
            display_affinity: w.display_affinity,
            width: w.width,
            height: w.height,
        };
        for window in windows {
            if !window.visible || window.cloaked || interview.contains(&window.pid) {
                continue;
            }
            if window.display_affinity != 0 {
                let key = (window.hwnd, window.display_affinity);
                excluded.insert(key);
                if !self.excluded.contains(&key) {
                    seen.push(Observation::CaptureExcludedWindow(sighting(window)));
                }
            }
            if window.topmost
                && window.layered
                && window.width >= OVERLAY_MIN_SIDE
                && window.height >= OVERLAY_MIN_SIDE
            {
                overlays.insert(window.hwnd);
                if !self.overlays.contains(&window.hwnd) {
                    seen.push(Observation::OverlayWindow(sighting(window)));
                }
            }
        }
        self.excluded = excluded;
        self.overlays = overlays;
        seen
    }
}

/// Remote sessions: reported when one starts or its kind changes.
#[derive(Debug, Default)]
pub struct RemoteTracker {
    last: (bool, bool),
}

impl RemoteTracker {
    pub fn update(
        &mut self,
        at_ms: i64,
        remote_session: bool,
        remote_control: bool,
    ) -> Vec<Observation> {
        let now = (remote_session, remote_control);
        let before = std::mem::replace(&mut self.last, now);
        let started = (remote_session && !before.0) || (remote_control && !before.1);
        if started {
            vec![Observation::RemoteSession(RemoteSession {
                at_ms,
                remote_session,
                remote_control,
            })]
        } else {
            Vec::new()
        }
    }
}
