//! The server's snapshot requests (`proctoring.md`, "Changes" 2026-10-11): read from the
//! heartbeat answer, each handed on once and never after it expired.

use hv_event_queue::{
    SNAPSHOT_TTL_MS, SnapshotKind, SnapshotRequest, SnapshotTracker, parse_rfc3339_ms, rfc3339_ms,
};
use serde_json::json;

const NOW: i64 = 1_791_000_000_000;

fn request(id: &str, kind: &str, requested_at_ms: i64) -> SnapshotRequest {
    serde_json::from_value(json!({
        "request_id": id,
        "event_id": "0b0e6f9c-0000-4000-8000-0000000000e1",
        "kind": kind,
        "requested_at": rfc3339_ms(requested_at_ms),
    }))
    .expect("a request")
}

#[test]
fn a_request_reads_its_kind_and_expiry() {
    let screen = request("0b0e6f9c-0000-4000-8000-000000000001", "screen", NOW);
    assert_eq!(screen.kind, SnapshotKind::Screen);
    assert_eq!(screen.kind.as_str(), "screen");
    assert_eq!(screen.expires_at_ms(), Some(NOW + SNAPSHOT_TTL_MS));
    let camera = request("0b0e6f9c-0000-4000-8000-000000000002", "camera", NOW);
    assert_eq!(camera.kind.as_str(), "camera");
}

#[test]
fn the_servers_microsecond_offset_times_are_read() {
    // Python's isoformat: microseconds and +00:00.
    assert_eq!(
        parse_rfc3339_ms("2026-10-12T05:01:02.120456+00:00"),
        parse_rfc3339_ms("2026-10-12T05:01:02.120Z")
    );
    assert_eq!(
        parse_rfc3339_ms("2026-10-12T05:01:02"),
        None,
        "a time zone is required"
    );
}

#[test]
fn each_request_is_handed_on_once() {
    let mut tracker = SnapshotTracker::default();
    let first = request(
        "0b0e6f9c-0000-4000-8000-000000000001",
        "screen",
        NOW - 1_000,
    );
    let second = request(
        "0b0e6f9c-0000-4000-8000-000000000002",
        "camera",
        NOW - 1_000,
    );
    assert!(tracker.accept(&first, NOW));
    assert!(
        !tracker.accept(&first, NOW + 5_000),
        "the next heartbeat repeats it"
    );
    assert!(tracker.accept(&second, NOW));
}

#[test]
fn expired_and_malformed_requests_are_dropped() {
    let mut tracker = SnapshotTracker::default();
    let old = request(
        "0b0e6f9c-0000-4000-8000-000000000003",
        "screen",
        NOW - SNAPSHOT_TTL_MS - 1,
    );
    assert!(!tracker.accept(&old, NOW));
    let mut no_zone = request("0b0e6f9c-0000-4000-8000-000000000004", "screen", NOW);
    no_zone.requested_at = "2026-10-12T05:01:02".into();
    assert!(!tracker.accept(&no_zone, NOW));
    let mut bad_id = request("0b0e6f9c-0000-4000-8000-000000000005", "screen", NOW);
    bad_id.request_id = "../../evidence".into();
    assert!(!tracker.accept(&bad_id, NOW));
}

#[test]
fn a_forgotten_request_can_come_again_and_old_ones_are_pruned() {
    let mut tracker = SnapshotTracker::default();
    let first = request("0b0e6f9c-0000-4000-8000-000000000001", "screen", NOW);
    assert!(tracker.accept(&first, NOW));
    tracker.forget(&first.request_id);
    assert!(
        tracker.accept(&first, NOW),
        "handing it on failed, so it may come again"
    );
    // Past its expiry the id is forgotten, so the tracker doesn't grow for ever.
    let later = NOW + SNAPSHOT_TTL_MS + 1;
    assert!(tracker.accept(
        &request("0b0e6f9c-0000-4000-8000-000000000009", "camera", later),
        later,
    ));
    assert_eq!(tracker.len(), 1, "only the new request is remembered");
}

#[test]
fn unknown_kinds_do_not_parse() {
    let value = json!({
        "request_id": "0b0e6f9c-0000-4000-8000-000000000001",
        "event_id": "0b0e6f9c-0000-4000-8000-0000000000e1",
        "kind": "microphone",
        "requested_at": "2026-10-12T05:01:02Z",
    });
    assert!(serde_json::from_value::<SnapshotRequest>(value).is_err());
}
