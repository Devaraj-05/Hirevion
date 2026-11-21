//! The apps to close before Start (owner, 2026-11-21: "ask the candidate to close all the
//! background and other applications"; ADR-0046).

use hv_event_queue::{AppRules, PolicyMatcher, apps_to_close};
use hv_monitor::{ProcessInfo, SignatureInfo};
use serde_json::json;

fn process(pid: u32, name: &str, titles: &[&str], interview_app: bool) -> ProcessInfo {
    ProcessInfo {
        pid,
        parent_pid: 1,
        name: name.to_owned(),
        path: Some(format!(r"C:\Apps\{name}")),
        start_time_ms: None,
        window_titles: titles.iter().map(|t| (*t).to_owned()).collect(),
        sha256: None,
        signature: SignatureInfo::default(),
        interview_app,
    }
}

fn matcher() -> PolicyMatcher {
    let rules: AppRules = serde_json::from_value(json!({
        "blocked": [
            { "match": "path", "value": r"C:\Apps\ChatGPT.exe", "category": "ai_assistant" },
        ],
    }))
    .expect("rules");
    PolicyMatcher::new(&rules)
}

#[test]
fn blocked_apps_must_close_and_other_open_windows_are_advice() {
    let running = [
        process(11, "ChatGPT.exe", &[], false),
        process(10, "ChatGPT.exe", &["ChatGPT"], false),
        process(20, "chrome.exe", &["Inbox - Mail"], false),
        process(21, "chrome.exe", &["Docs"], false),
        process(30, "svchost.exe", &[], false),
        process(40, "explorer.exe", &["Program Manager"], false),
        process(50, "AI-Interview.exe", &["Hirevion"], true),
    ];
    let apps = apps_to_close(&running, &matcher());
    let blocked: Vec<_> = apps.blocked.iter().map(|a| a.name.as_str()).collect();
    assert_eq!(blocked, ["ChatGPT.exe"], "once per app");
    assert_eq!(apps.blocked[0].category.as_deref(), Some("ai_assistant"));
    assert_eq!(apps.blocked[0].window_title.as_deref(), Some("ChatGPT"));
    let open: Vec<_> = apps.open.iter().map(|a| a.name.as_str()).collect();
    // Background processes, the Windows shell and the interview app itself are left out.
    assert_eq!(open, ["chrome.exe"]);
    assert_eq!(apps.open[0].window_title.as_deref(), Some("Inbox - Mail"));
}

#[test]
fn a_file_hash_is_needed_only_when_a_rule_matches_by_hash() {
    let rules =
        |value: serde_json::Value| -> AppRules { serde_json::from_value(value).expect("rules") };
    assert!(!rules(json!({ "blocked": [ { "match": "publisher", "value": "X" } ] })).uses_hash());
    assert!(rules(json!({ "blocked": [ { "match": "hash", "value": "ab" } ] })).uses_hash());
    assert!(rules(json!({ "allowed": [ { "match": "hash", "value": "ab" } ] })).uses_hash());
    assert!(
        rules(json!({ "blocked": [ { "match": "name", "value": "x",
                                     "with": [ { "match": "hash", "value": "ab" } ] } ] }))
        .uses_hash()
    );
}

#[test]
fn nothing_to_close() {
    let apps = apps_to_close(&[process(30, "svchost.exe", &[], false)], &matcher());
    assert!(apps.blocked.is_empty() && apps.open.is_empty());
}

#[test]
fn a_blocked_app_without_a_window_is_reported_but_never_blocks_start() {
    // A service the candidate can't close from the desktop (review, 2026-11-21).
    let rules: AppRules = serde_json::from_value(json!({
        "blocked": [
            { "match": "path", "value": r"C:\Apps\vmware-authd.exe", "category": "virtual_machine" },
            { "match": "path", "value": r"C:\Apps\ChatGPT.exe", "category": "ai_assistant" },
        ],
    }))
    .expect("rules");
    let apps = apps_to_close(
        &[
            process(10, "vmware-authd.exe", &[], false),
            process(20, "ChatGPT.exe", &[], false),
            process(21, "ChatGPT.exe", &["ChatGPT"], false),
        ],
        &PolicyMatcher::new(&rules),
    );
    let names = |list: &[hv_event_queue::AppToClose]| {
        list.iter().map(|a| a.name.clone()).collect::<Vec<_>>()
    };
    assert_eq!(names(&apps.blocked), ["ChatGPT.exe"]);
    assert_eq!(names(&apps.background), ["vmware-authd.exe"]);
    assert_eq!(
        apps.background[0].category.as_deref(),
        Some("virtual_machine")
    );
}

#[test]
fn file_facts_are_needed_where_a_rules_cheap_conditions_already_hold() {
    let rules: AppRules = serde_json::from_value(json!({
        "blocked": [
            { "match": "name", "value": "vmconnect",
              "with": [ { "match": "publisher", "value": "Microsoft Corporation" } ] },
            { "match": "publisher", "value": "TeamViewer Germany GmbH" },
            { "match": "path", "value": r"C:\Apps\" },
        ],
    }))
    .expect("rules");
    let matcher = PolicyMatcher::new(&rules);
    // Its name holds, so its signature decides.
    assert!(matcher.needs_file_facts(&process(1, "vmconnect.exe", &[], false)));
    // A rule on the path alone is decided without the file.
    assert!(!matcher.needs_file_facts(&process(2, "anything.exe", &[], false)));
    // A publisher-only rule has no cheap condition to narrow it down.
    assert!(!matcher.needs_file_facts(&process(3, "svchost.exe", &[], false)));
}
