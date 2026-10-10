//! The §61 app-rule matcher.

use hv_event_queue::{AppRules, MatchKind, PolicyMatcher, SessionPolicy, SeverityHint, Thresholds};
use hv_monitor::{ProcessInfo, SignatureInfo, SignatureKind, SignatureStatus};
use serde_json::json;

const ANYDESK_HASH: &str = "4f2a8a7c1e0b9d3c5a6f7e8d9c0b1a2f3e4d5c6b7a8f9e0d1c2b3a4f5e6d7c8b";
const ANYDESK_CERT: &str = "0011223344556677889900aabbccddeeff00112233445566778899aabbccddee";

fn anydesk() -> ProcessInfo {
    ProcessInfo {
        pid: 900,
        parent_pid: 1,
        name: "AnyDesk.exe".to_owned(),
        path: Some(r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe".to_owned()),
        start_time_ms: Some(1),
        window_titles: vec!["AnyDesk".to_owned()],
        sha256: Some(ANYDESK_HASH.to_owned()),
        signature: SignatureInfo {
            status: SignatureStatus::Valid,
            kind: Some(SignatureKind::Embedded),
            signer: Some("AnyDesk Software GmbH".to_owned()),
            signer_cert_sha256: Some(ANYDESK_CERT.to_owned()),
        },
        interview_app: false,
    }
}

fn rules(value: serde_json::Value) -> AppRules {
    serde_json::from_value(value).expect("app rules")
}

#[test]
fn a_blocked_publisher_matches_with_its_category_as_critical() {
    let matcher = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "publisher", "value": "anydesk software gmbh", "category": "remote_access" } ]
    })));
    let hit = matcher.evaluate(&anydesk()).expect("blocked");
    assert_eq!(hit.matched_by, MatchKind::Publisher);
    assert_eq!(hit.category.as_deref(), Some("remote_access"));
    assert_eq!(hit.severity_hint, SeverityHint::Critical);
    assert_eq!(hit.rule_index, 0);
}

#[test]
fn a_renamed_binary_is_still_caught_by_hash_or_signature() {
    let renamed = ProcessInfo {
        name: "notes.exe".to_owned(),
        path: Some(r"C:\Users\c\Downloads\notes.exe".to_owned()),
        window_titles: vec![],
        ..anydesk()
    };
    let by_hash = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "hash", "value": ANYDESK_HASH.to_uppercase() } ]
    })));
    let hit = by_hash.evaluate(&renamed).expect("blocked by hash");
    assert_eq!(hit.matched_by, MatchKind::Hash);
    assert_eq!(hit.severity_hint, SeverityHint::Warning, "no category");

    let by_signature = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "signature", "value": ANYDESK_CERT, "category": "remote_access" } ]
    })));
    assert_eq!(
        by_signature
            .evaluate(&renamed)
            .expect("blocked by signer")
            .matched_by,
        MatchKind::Signature
    );
}

#[test]
fn publisher_and_signature_rules_need_a_valid_signature() {
    let tampered = ProcessInfo {
        signature: SignatureInfo {
            status: SignatureStatus::Invalid,
            ..anydesk().signature
        },
        ..anydesk()
    };
    let matcher = PolicyMatcher::new(&rules(json!({
        "blocked": [
            { "match": "publisher", "value": "AnyDesk Software GmbH" },
            { "match": "signature", "value": ANYDESK_CERT }
        ]
    })));
    assert!(matcher.evaluate(&tampered).is_none());
}

#[test]
fn a_name_alone_never_blocks_but_a_name_with_another_attribute_does() {
    let name_only = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "name", "value": "AnyDesk.exe" } ]
    })));
    assert!(name_only.evaluate(&anydesk()).is_none());
    assert_eq!(name_only.ignored_name_only_rules(), 1);

    let with_title = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "name", "value": "anydesk", "with": [ { "match": "window_title", "value": "anydesk" } ] } ]
    })));
    assert!(with_title.evaluate(&anydesk()).is_some());
    let untitled = ProcessInfo {
        window_titles: vec![],
        ..anydesk()
    };
    assert!(with_title.evaluate(&untitled).is_none());
}

#[test]
fn paths_match_exactly_or_by_folder_and_titles_by_substring() {
    let matcher = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "path", "value": "c:/program files (x86)/anydesk/" } ]
    })));
    assert_eq!(
        matcher.evaluate(&anydesk()).expect("folder").matched_by,
        MatchKind::Path
    );
    let exact = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "path", "value": r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe" } ]
    })));
    assert!(exact.evaluate(&anydesk()).is_some());
    let other = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "path", "value": r"C:\Program Files (x86)\AnyDesk" } ]
    })));
    assert!(
        other.evaluate(&anydesk()).is_none(),
        "not a folder rule without the slash"
    );

    let title = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "window_title", "value": "ANYDESK" } ]
    })));
    assert_eq!(
        title.evaluate(&anydesk()).expect("title").matched_by,
        MatchKind::WindowTitle
    );
}

#[test]
fn an_allow_rule_only_overrides_an_equally_weak_or_weaker_block() {
    // Allowed by name, blocked by hash: renaming a blocked binary to an allowed name fails.
    let renamed_to_allowed = ProcessInfo {
        name: "Narrator.exe".to_owned(),
        ..anydesk()
    };
    let matcher = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "hash", "value": ANYDESK_HASH } ],
        "allowed": [ { "match": "name", "value": "Narrator.exe" } ]
    })));
    assert!(matcher.evaluate(&renamed_to_allowed).is_some());

    // Allowed by hash beats blocked by window title.
    let matcher = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "window_title", "value": "AnyDesk" } ],
        "allowed": [ { "match": "hash", "value": ANYDESK_HASH } ]
    })));
    assert!(matcher.evaluate(&anydesk()).is_none());
}

#[test]
fn the_interview_app_and_unknown_rule_kinds_never_match() {
    let interview = ProcessInfo {
        interview_app: true,
        ..anydesk()
    };
    let matcher = PolicyMatcher::new(&rules(json!({
        "blocked": [
            { "match": "hash", "value": ANYDESK_HASH },
            { "match": "certificate_policy", "value": "x" }
        ]
    })));
    assert!(matcher.evaluate(&interview).is_none());
    let unknown_only = PolicyMatcher::new(&rules(json!({
        "blocked": [ { "match": "certificate_policy", "value": "x" } ]
    })));
    assert!(unknown_only.evaluate(&anydesk()).is_none());
}

#[test]
fn the_session_policy_parses_the_contract_example_and_feeds_thresholds() {
    let policy: SessionPolicy = serde_json::from_value(json!({
        "proctor_session_id": "4b1f2f3e-0000-4000-8000-000000000001",
        "policy_version": 3,
        "level": "standard",
        "checks": ["face", "focus", "gaze", "phone", "processes", "displays"],
        "thresholds": {
            "FACE_ABSENT": { "warn_after_ms": 5000, "critical_after_ms": 30000 },
            "APPLICATION_FOCUS_CHANGE": { "warn_after_ms": 4000 }
        },
        "app_rules": {
            "blocked": [ { "match": "publisher", "value": "Example Corp", "category": "remote_access" } ],
            "allowed": [ { "match": "path", "value": "C:\\Windows\\System32\\Narrator.exe" } ]
        },
        "single_display": false,
        "heartbeat_seconds": 5,
        "batch_max_events": 100,
        "accommodations": ["relaxed_gaze"]
    }))
    .expect("policy");
    assert_eq!(policy.batch_max_events, 100);
    assert_eq!(policy.app_rules.blocked.len(), 1);
    let thresholds = Thresholds::from_policy(&policy);
    assert_eq!(thresholds.focus_away_ms, 4000);
    assert_eq!(thresholds.minimized_ms, 3000, "the §6.12 default");
    let watch = policy.monitor_watch();
    assert!(watch.processes && watch.focus && watch.displays);
    assert!(
        watch.windows && watch.remote_session,
        "integrity checks always run"
    );

    let minimal = SessionPolicy {
        checks: vec!["face".to_owned()],
        ..policy
    };
    let watch = minimal.monitor_watch();
    assert!(!watch.processes && !watch.focus && !watch.displays);
}
