//! Closing the window during an interview (C8-9; moved out of the webview 2026-11-26).
//!
//! Closing mid-interview ends it for good, so the page asks first, as End Interview does. The
//! webview used to ask through `onCloseRequested`, but Tauri keeps a page's JavaScript
//! listeners after the page reloads: once the dev server reloaded the page mid-interview, every
//! close went to a listener that no longer existed and the window couldn't be closed at all.
//! Now the app decides: it asks the page only while the page says an interview is live, a
//! reload clears that, and a page that doesn't answer within [`UNANSWERED`] can't hold the
//! window (a second close then closes it).

use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use tauri::{Emitter, Manager, Runtime};

/// How long a page has to answer a close request before the next request closes the window.
pub const UNANSWERED: Duration = Duration::from_secs(3);

/// The event the page receives when the window is asked to close mid-interview.
pub const CLOSE_REQUESTED_EVENT: &str = "hv://close-requested";

/// What to do with a close request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CloseDecision {
    /// Let the window close.
    Close,
    /// Keep it open and ask the page (it shows the End Interview confirmation).
    Ask,
}

#[derive(Debug, Default)]
struct GuardState {
    live: bool,
    asked_at: Option<Instant>,
}

/// Whether a close must be confirmed by the page first.
#[derive(Debug, Default)]
pub struct CloseGuard {
    state: Mutex<GuardState>,
}

impl CloseGuard {
    /// The page starts (`true`) or leaves (`false`) a live interview.
    pub fn set_live(&self, live: bool) {
        *self.lock() = GuardState {
            live,
            asked_at: None,
        };
    }

    /// The page received the close request and is asking the candidate.
    pub fn answered(&self) {
        self.lock().asked_at = None;
    }

    /// A page (re)load: whatever the old page said no longer holds.
    pub fn page_loaded(&self) {
        self.set_live(false);
    }

    /// Decides a close request made at `now`.
    pub fn on_close_requested(&self, now: Instant) -> CloseDecision {
        let mut state = self.lock();
        if !state.live {
            return CloseDecision::Close;
        }
        match state.asked_at {
            Some(asked) if now.saturating_duration_since(asked) >= UNANSWERED => {
                // The page never answered: it's gone or stuck, and mustn't trap the candidate.
                *state = GuardState::default();
                CloseDecision::Close
            }
            Some(_) => CloseDecision::Ask,
            None => {
                state.asked_at = Some(now);
                CloseDecision::Ask
            }
        }
    }

    fn lock(&self) -> MutexGuard<'_, GuardState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// The page starts (`live: true`) or leaves a live interview.
#[tauri::command]
pub fn close_guard_live(guard: tauri::State<'_, CloseGuard>, live: bool) {
    guard.set_live(live);
}

/// The page received [`CLOSE_REQUESTED_EVENT`] and is asking the candidate.
#[tauri::command]
pub fn close_guard_answered(guard: tauri::State<'_, CloseGuard>) {
    guard.answered();
}

/// The window's close button, Alt+F4 or the taskbar: asks the page while an interview is live.
pub fn on_window_event<R: Runtime>(window: &tauri::Window<R>, event: &tauri::WindowEvent) {
    let tauri::WindowEvent::CloseRequested { api, .. } = event else {
        return;
    };
    let Some(guard) = window.try_state::<CloseGuard>() else {
        return;
    };
    if guard.on_close_requested(Instant::now()) == CloseDecision::Ask {
        api.prevent_close();
        if let Err(error) = window.emit(CLOSE_REQUESTED_EVENT, ()) {
            eprintln!("close guard: couldn't ask the page: {error}");
        }
    }
}

/// Every page load starts with no live interview.
pub fn on_page_load<R: Runtime>(
    webview: &tauri::Webview<R>,
    payload: &tauri::webview::PageLoadPayload<'_>,
) {
    if payload.event() == tauri::webview::PageLoadEvent::Started
        && let Some(guard) = webview.try_state::<CloseGuard>()
    {
        guard.page_loaded();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closes_when_no_interview_is_live() {
        let guard = CloseGuard::default();
        assert_eq!(
            guard.on_close_requested(Instant::now()),
            CloseDecision::Close
        );
    }

    #[test]
    fn asks_the_page_during_an_interview() {
        let guard = CloseGuard::default();
        guard.set_live(true);
        let now = Instant::now();
        assert_eq!(guard.on_close_requested(now), CloseDecision::Ask);
        guard.answered();
        // The candidate chose to continue, then closes again later: asked again.
        let later = now + Duration::from_secs(60);
        assert_eq!(guard.on_close_requested(later), CloseDecision::Ask);
    }

    #[test]
    fn a_page_that_never_answers_cant_hold_the_window() {
        let guard = CloseGuard::default();
        guard.set_live(true);
        let now = Instant::now();
        assert_eq!(guard.on_close_requested(now), CloseDecision::Ask);
        assert_eq!(
            guard.on_close_requested(now + Duration::from_secs(1)),
            CloseDecision::Ask,
            "a slow page still gets its time"
        );
        assert_eq!(
            guard.on_close_requested(now + UNANSWERED),
            CloseDecision::Close
        );
    }

    #[test]
    fn a_reloaded_page_releases_the_window() {
        let guard = CloseGuard::default();
        guard.set_live(true);
        guard.page_loaded();
        assert_eq!(
            guard.on_close_requested(Instant::now()),
            CloseDecision::Close
        );
    }

    #[test]
    fn leaving_the_interview_releases_the_window() {
        let guard = CloseGuard::default();
        guard.set_live(true);
        guard.set_live(false);
        assert_eq!(
            guard.on_close_requested(Instant::now()),
            CloseDecision::Close
        );
    }
}
