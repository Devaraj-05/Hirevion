//! The wire format of events.

use hv_event_queue::{EventDraft, EventName, ProctorEvent, Source, rfc3339_ms};
use serde_json::json;

#[test]
fn timestamps_are_rfc3339_utc_with_milliseconds() {
    assert_eq!(rfc3339_ms(0), "1970-01-01T00:00:00.000Z");
    assert_eq!(rfc3339_ms(1_791_781_262_120), "2026-10-12T05:01:02.120Z");
    assert_eq!(rfc3339_ms(951_782_400_000), "2000-02-29T00:00:00.000Z");
    assert_eq!(rfc3339_ms(-1), "1969-12-31T23:59:59.999Z");
}

#[test]
fn an_event_serialises_exactly_as_the_contract_shows() {
    let event = EventDraft::new(
        EventName::ApplicationFocusChange,
        Source::Native,
        1_791_781_262_120,
    )
    .duration_ms(3400)
    .details(json!({ "previous_app": "AI-Interview.exe", "new_app": "chrome.exe" }))
    .into_event(41);
    assert_eq!(
        serde_json::to_value(&event).expect("json"),
        json!({
            "seq": 41,
            "event": "APPLICATION_FOCUS_CHANGE",
            "source": "native",
            "started_at": "2026-10-12T05:01:02.120Z",
            "duration_ms": 3400,
            "confidence": 1.0,
            "evidence": [],
            "details": { "previous_app": "AI-Interview.exe", "new_app": "chrome.exe" }
        })
    );
    let back: ProctorEvent =
        serde_json::from_value(serde_json::to_value(&event).expect("json")).expect("round trip");
    assert_eq!(back, event);
}

#[test]
fn every_name_matches_its_wire_form_and_unknown_names_are_refused() {
    for name in [
        EventName::VmDetected,
        EventName::CaptureExcludedWindow,
        EventName::UnexpectedPersonDetected,
        EventName::EditorFocusChange,
        EventName::MicReconnected,
    ] {
        assert_eq!(
            serde_json::to_value(name).expect("json"),
            json!(name.as_str())
        );
    }
    assert_eq!(
        serde_json::to_value(Source::ThirdEye).expect("json"),
        json!("third_eye")
    );
    assert!(serde_json::from_value::<EventName>(json!("DEVICE_CHANGE")).is_err());
}
