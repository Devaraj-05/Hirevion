//! The apps to close before the interview starts (owner, 2026-11-21: "ask the candidate to
//! close all the background and other applications"; ADR-0046).
//!
//! The ones the interview's policy blocks must be closed before Start: they are matched with
//! the same [`PolicyMatcher`] the interview reports `BLOCKED_PROCESS_DETECTED` with. Other apps
//! with a window are listed as advice. Background processes without a window, the Windows shell
//! and the interview app itself are left out.

use std::collections::HashSet;

use hv_monitor::ProcessInfo;
use serde::Serialize;

use crate::policy::PolicyMatcher;

/// Windows' own processes that show a window without being an app the candidate opened.
const SHELL: &[&str] = &[
    "explorer.exe",
    "textinputhost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "searchhost.exe",
    "lockapp.exe",
    "applicationframehost.exe",
    "systemsettings.exe",
];

/// One app, once however many processes it runs.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AppToClose {
    pub name: String,
    /// Its first window's title, to recognise it by.
    pub window_title: Option<String>,
    /// The blocked rule's category (`ai_assistant`, `remote_access`…), for a blocked app.
    pub category: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct AppsToClose {
    /// Blocked by the interview's policy and showing a window: Start waits until they are
    /// closed.
    pub blocked: Vec<AppToClose>,
    /// Blocked but without a window (a service, a tray app): the candidate may not be able to
    /// stop them, so they never hold Start back; the monitor reports them if they still run.
    pub background: Vec<AppToClose>,
    /// Other apps with a window: closing them is advised.
    pub open: Vec<AppToClose>,
}

pub fn apps_to_close(processes: &[ProcessInfo], matcher: &PolicyMatcher) -> AppsToClose {
    let mut apps = AppsToClose::default();
    // Each blocked app once, whatever its processes: with a window if any of them has one.
    let mut blocked: Vec<(String, AppToClose)> = Vec::new();
    for process in processes.iter().filter(|p| !p.interview_app) {
        let Some(hit) = matcher.evaluate(process) else {
            continue;
        };
        let key = process.name.to_lowercase();
        let title = process.window_titles.first().cloned();
        match blocked.iter_mut().find(|(known, _)| *known == key) {
            Some((_, app)) => {
                if app.window_title.is_none() {
                    app.window_title = title;
                }
            }
            None => blocked.push((
                key,
                AppToClose {
                    name: process.name.clone(),
                    window_title: title,
                    category: hit.category,
                },
            )),
        }
    }
    let mut seen: HashSet<String> = blocked.iter().map(|(key, _)| key.clone()).collect();
    for (_, app) in blocked {
        if app.window_title.is_some() {
            apps.blocked.push(app);
        } else {
            apps.background.push(app);
        }
    }
    for process in processes.iter().filter(|p| !p.interview_app) {
        let name = process.name.to_lowercase();
        if process.window_titles.is_empty() || SHELL.contains(&name.as_str()) {
            continue;
        }
        if seen.insert(name) {
            apps.open.push(AppToClose {
                name: process.name.clone(),
                window_title: process.window_titles.first().cloned(),
                category: None,
            });
        }
    }
    apps
}
