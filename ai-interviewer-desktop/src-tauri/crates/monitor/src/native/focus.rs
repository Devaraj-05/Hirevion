//! Focus tracking (§62): a thread with its own message loop receives out-of-context WinEvents
//! for foreground changes and minimise/restore. Only window-level events are hooked; no input
//! of any kind is observed.

use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::mpsc::{self, Sender};
use std::thread::JoinHandle;
use std::time::Instant;

use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::System::Threading::GetCurrentThreadId;
use windows::Win32::UI::Accessibility::{HWINEVENTHOOK, SetWinEventHook, UnhookWinEvent};
use windows::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZEEND,
    EVENT_SYSTEM_MINIMIZESTART, GetForegroundWindow, GetMessageW, MSG, PM_NOREMOVE, PeekMessageW,
    PostThreadMessageW, WINEVENT_OUTOFCONTEXT, WM_QUIT, WM_USER,
};

use super::processes::{image_path, snapshot};
use super::windows::{owner_pid, title};
use super::{OwnedHandle, processes};
use crate::monitor::{Clock, Ready, ReadyGuard};
use crate::observation::{AppRef, FocusChange, MinimizeChange, Observation};
use crate::track::interview_tree;

/// `OBJID_WINDOW` and `CHILDID_SELF`: the event is about the window itself.
const OBJID_WINDOW: i32 = 0;
const CHILDID_SELF: i32 = 0;
/// The process-name cache is cleared when it grows past this (PIDs get reused).
const NAME_CACHE_LIMIT: usize = 512;

/// The running focus thread.
pub(crate) struct FocusThread {
    thread_id: u32,
    join: JoinHandle<()>,
}

impl FocusThread {
    pub(crate) fn spawn(
        clock: Clock,
        interview_pid: u32,
        observations: Sender<Observation>,
        ready: Arc<Ready>,
    ) -> std::io::Result<Self> {
        let (started, thread_id) = mpsc::channel();
        let join = std::thread::Builder::new()
            .name("hv-monitor-focus".into())
            .spawn(move || {
                let mut ready = ready.guard();
                run(clock, interview_pid, observations, &started, &mut ready);
            })?;
        let thread_id = thread_id
            .recv()
            .map_err(|_| std::io::Error::other("the focus thread ended at start"))?;
        Ok(Self { thread_id, join })
    }

    /// Ends the message loop and waits for the thread.
    pub(crate) fn stop(self) {
        // SAFETY: posts WM_QUIT to a thread whose queue exists (created before its id was
        // sent); if the thread already ended, the call fails harmlessly.
        let _ = unsafe { PostThreadMessageW(self.thread_id, WM_QUIT, WPARAM(0), LPARAM(0)) };
        let _ = self.join.join();
    }
}

struct State {
    clock: Clock,
    interview_pid: u32,
    observations: Sender<Observation>,
    foreground: Option<(AppRef, Instant)>,
    names: HashMap<u32, String>,
}

thread_local! {
    static STATE: RefCell<Option<State>> = const { RefCell::new(None) };
}

fn run(
    clock: Clock,
    interview_pid: u32,
    observations: Sender<Observation>,
    started: &Sender<u32>,
    ready: &mut ReadyGuard,
) {
    let mut message = MSG::default();
    // SAFETY: creates this thread's message queue so WM_QUIT can be posted to it; `message`
    // is a live MSG.
    let _ = unsafe { PeekMessageW(&raw mut message, None, WM_USER, WM_USER, PM_NOREMOVE) };
    // SAFETY: takes no arguments.
    let thread_id = unsafe { GetCurrentThreadId() };

    STATE.with(|state| {
        *state.borrow_mut() = Some(State {
            clock,
            interview_pid,
            observations,
            foreground: None,
            names: HashMap::new(),
        });
    });
    // The window in front when monitoring starts.
    // SAFETY: takes no arguments; a null result means no foreground window.
    let current = unsafe { GetForegroundWindow() };
    if !current.is_invalid() {
        with_state(|state| state.foreground_changed(current));
    }

    // SAFETY: an out-of-context hook with a valid callback; events are delivered to this
    // thread's message loop, and the hooks are removed before the thread ends.
    let hooks: Vec<HWINEVENTHOOK> = unsafe {
        [
            SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND,
                EVENT_SYSTEM_FOREGROUND,
                None,
                Some(on_event),
                0,
                0,
                WINEVENT_OUTOFCONTEXT,
            ),
            SetWinEventHook(
                EVENT_SYSTEM_MINIMIZESTART,
                EVENT_SYSTEM_MINIMIZEEND,
                None,
                Some(on_event),
                0,
                0,
                WINEVENT_OUTOFCONTEXT,
            ),
        ]
    }
    .into_iter()
    .filter(|hook| !hook.is_invalid())
    .collect();
    let _ = started.send(thread_id);
    ready.done();

    loop {
        // SAFETY: `message` is a live MSG; this thread owns its queue.
        let got = unsafe { GetMessageW(&raw mut message, None, 0, 0) };
        if got.0 <= 0 {
            break;
        }
        // SAFETY: `message` was just filled by GetMessageW.
        unsafe { DispatchMessageW(&raw const message) };
    }
    for hook in hooks {
        // SAFETY: each hook was installed above and is removed once.
        let _ = unsafe { UnhookWinEvent(hook) };
    }
    STATE.with(|state| state.borrow_mut().take());
}

fn with_state(f: impl FnOnce(&mut State)) {
    STATE.with(|state| {
        if let Ok(mut state) = state.try_borrow_mut()
            && let Some(state) = state.as_mut()
        {
            f(state);
        }
    });
}

unsafe extern "system" fn on_event(
    _hook: HWINEVENTHOOK,
    event: u32,
    hwnd: HWND,
    object: i32,
    child: i32,
    _thread: u32,
    _time: u32,
) {
    if object != OBJID_WINDOW || child != CHILDID_SELF || hwnd.is_invalid() {
        return;
    }
    with_state(|state| match event {
        EVENT_SYSTEM_FOREGROUND => state.foreground_changed(hwnd),
        EVENT_SYSTEM_MINIMIZESTART => state.minimized(hwnd, true),
        EVENT_SYSTEM_MINIMIZEEND => state.minimized(hwnd, false),
        _ => {}
    });
}

impl State {
    fn foreground_changed(&mut self, hwnd: HWND) {
        let app = self.app(hwnd);
        if self
            .foreground
            .as_ref()
            .is_some_and(|(current, _)| current.pid == app.pid)
        {
            return;
        }
        let previous = self.foreground.replace((app.clone(), Instant::now()));
        let observation = Observation::FocusChanged(FocusChange {
            at_ms: (self.clock)(),
            previous_duration_ms: previous
                .as_ref()
                .map(|(_, since)| u64::try_from(since.elapsed().as_millis()).unwrap_or(u64::MAX)),
            previous: previous.map(|(app, _)| app),
            new: app,
        });
        let _ = self.observations.send(observation);
    }

    fn minimized(&mut self, hwnd: HWND, minimized: bool) {
        let observation = Observation::Minimize(MinimizeChange {
            at_ms: (self.clock)(),
            app: self.app(hwnd),
            minimized,
        });
        let _ = self.observations.send(observation);
    }

    fn app(&mut self, hwnd: HWND) -> AppRef {
        let pid = owner_pid(hwnd);
        if self.names.len() > NAME_CACHE_LIMIT {
            self.names.clear();
        }
        let name = self
            .names
            .entry(pid)
            .or_insert_with(|| process_name(pid))
            .clone();
        let interview_app = self.interview_pid != 0
            && (pid == self.interview_pid
                || (name.eq_ignore_ascii_case("msedgewebview2.exe")
                    && interview_tree(&snapshot(), self.interview_pid).contains(&pid)));
        AppRef {
            pid,
            name,
            window_title: title(hwnd),
            interview_app,
        }
    }
}

/// The executable file name of a process, or empty when it can't be opened.
fn process_name(pid: u32) -> String {
    use windows::Win32::System::Threading::{OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION};
    // SAFETY: takes an access mask, a flag and a PID; the handle is owned below.
    let Ok(handle) = (unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }) else {
        return processes::snapshot()
            .into_iter()
            .find(|e| e.pid == pid)
            .map(|e| e.name)
            .unwrap_or_default();
    };
    let process = OwnedHandle(handle);
    image_path(&process)
        .and_then(|path| {
            std::path::Path::new(&path)
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
        })
        .unwrap_or_default()
}
