//! Starting and stopping the watcher threads.

use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Condvar, Mutex, PoisonError};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::observation::Observation;
use crate::virtual_devices::VirtualDeviceCatalogue;

/// The time source for every observation, in milliseconds since the Unix epoch. The app passes
/// `ApiClient::server_now_ms`, so events carry server time.
pub type Clock = Arc<dyn Fn() -> i64 + Send + Sync>;

/// This machine's clock.
pub fn system_clock() -> Clock {
    Arc::new(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| i64::try_from(d.as_millis()).unwrap_or(i64::MAX))
    })
}

/// Which watchers run. The session policy's `checks` decide (see `hv-event-queue`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Watch {
    /// Process starts and exits with §60's metadata, and their window titles.
    pub processes: bool,
    /// Foreground changes and minimise/restore.
    pub focus: bool,
    pub displays: bool,
    /// Cameras and microphones, virtual ones included.
    pub devices: bool,
    /// Windows hidden from capture, and overlays.
    pub windows: bool,
    pub remote_session: bool,
    pub virtual_machine: bool,
    /// The integrity findings handed in, and a debugger attaching later.
    pub integrity: bool,
}

impl Watch {
    pub const fn all() -> Self {
        Self {
            processes: true,
            focus: true,
            displays: true,
            devices: true,
            windows: true,
            remote_session: true,
            virtual_machine: true,
            integrity: true,
        }
    }

    pub const fn none() -> Self {
        Self {
            processes: false,
            focus: false,
            displays: false,
            devices: false,
            windows: false,
            remote_session: false,
            virtual_machine: false,
            integrity: false,
        }
    }
}

impl Default for Watch {
    fn default() -> Self {
        Self::all()
    }
}

/// How the monitor runs.
#[derive(Clone)]
pub struct MonitorConfig {
    pub clock: Clock,
    /// The interview app's PID: it and its descendants are "the interview app" for focus, and
    /// never count as another process. `0` means none (tests).
    pub interview_pid: u32,
    /// How often the process list is read (the SP-11 bound is 2 s from start to event).
    pub process_poll: Duration,
    /// How often displays, devices, windows and the session are scanned.
    pub environment_poll: Duration,
    pub watch: Watch,
    pub virtual_devices: VirtualDeviceCatalogue,
    /// Integrity findings the app made before the monitor started, as `(reason, detail)`:
    /// `("webview_environment", Some("WEBVIEW2_…"))`, `("debugger_attached", None)`.
    pub startup_integrity: Vec<(String, Option<String>)>,
}

impl Default for MonitorConfig {
    fn default() -> Self {
        Self {
            clock: system_clock(),
            interview_pid: std::process::id(),
            process_poll: Duration::from_millis(500),
            environment_poll: Duration::from_secs(1),
            watch: Watch::all(),
            virtual_devices: VirtualDeviceCatalogue::default(),
            startup_integrity: Vec::new(),
        }
    }
}

impl std::fmt::Debug for MonitorConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MonitorConfig")
            .field("interview_pid", &self.interview_pid)
            .field("process_poll", &self.process_poll)
            .field("environment_poll", &self.environment_poll)
            .field("watch", &self.watch)
            .field("startup_integrity", &self.startup_integrity)
            .finish_non_exhaustive()
    }
}

/// Counts the watchers that haven't finished their first scan.
#[derive(Debug, Default)]
pub(crate) struct Ready {
    pending: Mutex<usize>,
    changed: Condvar,
}

impl Ready {
    fn expect(&self, watchers: usize) {
        *self.pending.lock().unwrap_or_else(PoisonError::into_inner) = watchers;
    }

    /// Marks one watcher ready when dropped, even if it ends early.
    pub(crate) fn guard(self: &Arc<Self>) -> ReadyGuard {
        ReadyGuard(Some(self.clone()))
    }

    fn done(&self) {
        let mut pending = self.pending.lock().unwrap_or_else(PoisonError::into_inner);
        *pending = pending.saturating_sub(1);
        self.changed.notify_all();
    }

    fn wait(&self, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        let mut pending = self.pending.lock().unwrap_or_else(PoisonError::into_inner);
        while *pending > 0 {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return false;
            }
            pending = self
                .changed
                .wait_timeout(pending, left)
                .unwrap_or_else(PoisonError::into_inner)
                .0;
        }
        true
    }
}

pub(crate) struct ReadyGuard(Option<Arc<Ready>>);

impl ReadyGuard {
    /// Marks the watcher ready now.
    pub(crate) fn done(&mut self) {
        if let Some(ready) = self.0.take() {
            ready.done();
        }
    }
}

impl Drop for ReadyGuard {
    fn drop(&mut self) {
        self.done();
    }
}

/// Wakes sleeping watchers when the monitor stops.
#[derive(Debug, Default)]
pub(crate) struct StopSignal {
    stopped: Mutex<bool>,
    changed: Condvar,
}

impl StopSignal {
    fn stop(&self) {
        *self.stopped.lock().unwrap_or_else(PoisonError::into_inner) = true;
        self.changed.notify_all();
    }

    /// Sleeps for `period` or until stopped; `true` when stopped.
    pub(crate) fn wait(&self, period: Duration) -> bool {
        let stopped = self.stopped.lock().unwrap_or_else(PoisonError::into_inner);
        let (stopped, _) = self
            .changed
            .wait_timeout_while(stopped, period, |stopped| !*stopped)
            .unwrap_or_else(PoisonError::into_inner);
        *stopped
    }
}

/// Starts the monitor.
#[derive(Debug)]
pub struct Monitor;

impl Monitor {
    /// Starts the watchers chosen in `config.watch`, each on its own thread, and returns the
    /// handle that stops them and the channel they report on. The channel closes once every
    /// watcher has stopped.
    pub fn start(config: MonitorConfig) -> std::io::Result<(MonitorHandle, Receiver<Observation>)> {
        imp::start(config)
    }
}

/// The running monitor. Stopping (or dropping) it ends every watcher.
pub struct MonitorHandle {
    stop: Arc<StopSignal>,
    ready: Arc<Ready>,
    threads: Vec<JoinHandle<()>>,
    #[cfg(windows)]
    focus: Option<crate::native::focus::FocusThread>,
}

impl std::fmt::Debug for MonitorHandle {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MonitorHandle")
            .field("threads", &self.threads.len())
            .finish_non_exhaustive()
    }
}

impl MonitorHandle {
    /// Waits until every watcher finished its first scan (the process watcher hashes and
    /// verifies every running executable once). `false` on timeout.
    pub fn wait_ready(&self, timeout: Duration) -> bool {
        self.ready.wait(timeout)
    }

    /// Stops every watcher and waits for the threads.
    pub fn stop(mut self) {
        self.shutdown();
    }

    fn shutdown(&mut self) {
        self.stop.stop();
        #[cfg(windows)]
        if let Some(focus) = self.focus.take() {
            focus.stop();
        }
        for thread in self.threads.drain(..) {
            let _ = thread.join();
        }
    }
}

impl Drop for MonitorHandle {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[cfg(not(windows))]
mod imp {
    use super::*;

    pub(super) fn start(
        _config: MonitorConfig,
    ) -> std::io::Result<(MonitorHandle, Receiver<Observation>)> {
        Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "native monitoring runs on Windows only",
        ))
    }
}

#[cfg(windows)]
mod imp {
    use std::collections::HashMap;
    use std::sync::mpsc::Sender;

    use super::*;
    use crate::file_cache::FileCache;
    use crate::native::{self, local_now_ms};
    use crate::observation::{IntegrityFinding, VirtualMachine};
    use crate::track::{
        DeviceTracker, DisplayTracker, ProcessTracker, RemoteTracker, WindowTracker, interview_tree,
    };

    const DEBUGGER_ATTACHED: &str = "debugger_attached";

    pub(super) fn start(
        config: MonitorConfig,
    ) -> std::io::Result<(MonitorHandle, Receiver<Observation>)> {
        let (sender, receiver) = mpsc::channel();
        let stop = Arc::new(StopSignal::default());
        let ready = Arc::new(Ready::default());
        let watch = config.watch;
        let environment = watch.displays
            || watch.devices
            || watch.windows
            || watch.remote_session
            || watch.virtual_machine
            || watch.integrity;
        ready.expect(
            usize::from(watch.processes) + usize::from(watch.focus) + usize::from(environment),
        );

        let mut handle = MonitorHandle {
            stop: stop.clone(),
            ready: ready.clone(),
            threads: Vec::new(),
            focus: None,
        };
        if watch.processes {
            let (config, sender, stop, guard) =
                (config.clone(), sender.clone(), stop.clone(), ready.guard());
            handle.threads.push(
                std::thread::Builder::new()
                    .name("hv-monitor-processes".into())
                    .spawn(move || processes(&config, &sender, &stop, guard))?,
            );
        }
        if environment {
            let (config, sender, stop, guard) =
                (config.clone(), sender.clone(), stop.clone(), ready.guard());
            handle.threads.push(
                std::thread::Builder::new()
                    .name("hv-monitor-environment".into())
                    .spawn(move || environment_loop(&config, &sender, &stop, guard))?,
            );
        }
        if watch.focus {
            handle.focus = Some(native::focus::FocusThread::spawn(
                config.clock.clone(),
                config.interview_pid,
                sender,
                ready,
            )?);
        }
        Ok((handle, receiver))
    }

    fn send_all(sender: &Sender<Observation>, observations: Vec<Observation>) -> bool {
        observations.into_iter().all(|o| sender.send(o).is_ok())
    }

    fn processes(
        config: &MonitorConfig,
        sender: &Sender<Observation>,
        stop: &StopSignal,
        mut ready: ReadyGuard,
    ) {
        let mut tracker = ProcessTracker::default();
        let mut cache = FileCache::new(native::signature::verify);
        loop {
            let entries = native::processes::snapshot();
            let titles = native::windows::titles_by_pid();
            let now = (config.clock)();
            let offset = now - local_now_ms();
            let seen = tracker.update(
                now,
                &entries,
                &titles,
                config.interview_pid,
                |entry, titles, interview| {
                    native::processes::describe(entry, titles, interview, &mut cache, offset)
                },
            );
            if !send_all(sender, seen) {
                return;
            }
            ready.done();
            if stop.wait(config.process_poll) {
                return;
            }
        }
    }

    fn environment_loop(
        config: &MonitorConfig,
        sender: &Sender<Observation>,
        stop: &StopSignal,
        mut ready: ReadyGuard,
    ) {
        let watch = config.watch;
        let clock = &config.clock;
        let media = if watch.devices {
            native::devices::MediaSession::start().ok()
        } else {
            None
        };
        let mut displays = DisplayTracker::default();
        let mut devices = DeviceTracker::new(config.virtual_devices.clone());
        let mut windows = WindowTracker::default();
        let mut remote = RemoteTracker::default();
        let mut debugger_reported = false;

        let mut once = Vec::new();
        if watch.integrity {
            for (reason, detail) in &config.startup_integrity {
                debugger_reported |= reason == DEBUGGER_ATTACHED;
                once.push(Observation::ClientIntegrity(IntegrityFinding {
                    at_ms: clock(),
                    reason: reason.clone(),
                    detail: detail.clone(),
                }));
            }
        }
        if watch.virtual_machine {
            let (present, vendor) = native::environment::hypervisor();
            if present {
                once.push(Observation::VirtualMachine(VirtualMachine {
                    at_ms: clock(),
                    hypervisor_present: present,
                    vendor,
                }));
            }
        }
        if !send_all(sender, once) {
            return;
        }

        loop {
            let mut seen = Vec::new();
            if watch.displays
                && let Some(list) = native::displays::enumerate()
            {
                seen.extend(displays.update(clock(), list));
            }
            if let Some(media) = &media
                && let Some(list) = media.enumerate()
            {
                seen.extend(devices.update(clock(), list));
            }
            if watch.windows {
                let entries = native::processes::snapshot();
                let tree = interview_tree(&entries, config.interview_pid);
                let names: HashMap<u32, String> =
                    entries.into_iter().map(|e| (e.pid, e.name)).collect();
                seen.extend(windows.update(clock(), &native::windows::scan(&names), &tree));
            }
            if watch.remote_session {
                let (session, control) = native::environment::remote();
                seen.extend(remote.update(clock(), session, control));
            }
            if watch.integrity && !debugger_reported && hv_security::integrity::debugger_present() {
                debugger_reported = true;
                seen.push(Observation::ClientIntegrity(IntegrityFinding {
                    at_ms: clock(),
                    reason: DEBUGGER_ATTACHED.to_owned(),
                    detail: None,
                }));
            }
            if !send_all(sender, seen) {
                return;
            }
            ready.done();
            if stop.wait(config.environment_poll) {
                return;
            }
        }
    }
}
