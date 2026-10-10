//! The pure parts of proctoring in the app (SP-11 wiring): what the webview may hand in, how
//! the heartbeat's device status is worked out, and what the monitor starts with.

use hv_event_queue::{DeviceStatus, EventDraft, EventName, Source};
use serde::Deserialize;
use serde_json::{Map, Value};

use super::error::{CommandError, CommandResult};

/// The most a face event's `details` may weigh once serialised. The face module sends a few
/// numbers; anything bigger isn't from it.
const MAX_DETAILS_BYTES: usize = 4096;
/// The longest device name taken from the webview.
const MAX_LABEL_CHARS: usize = 200;

/// A camera event as the face module emits it (`CameraEvent`, no `seq`). Fields it has that
/// the native side doesn't take (`evidence`: snapshots are uploaded natively) are ignored.
#[derive(Debug, Clone, Deserialize)]
pub struct FaceEvent {
    pub event: EventName,
    pub source: Source,
    /// Server time, RFC 3339 (`toISOString()` shifted by the recording clock's offset).
    pub started_at: String,
    #[serde(default)]
    pub duration_ms: Option<u64>,
    #[serde(default = "full_confidence")]
    pub confidence: f64,
    #[serde(default)]
    pub details: Map<String, Value>,
}

fn full_confidence() -> f64 {
    1.0
}

/// The events the webview's camera analysis may raise. The webview is not trusted with the
/// native events (processes, focus, devices…): those come from the monitor.
fn is_camera_event(event: EventName) -> bool {
    matches!(
        event,
        EventName::FaceAbsent
            | EventName::MultipleFaces
            | EventName::FaceTooFar
            | EventName::FaceTooClose
            | EventName::GazeDeviation
            | EventName::CameraObstructed
            | EventName::PhoneDetected
            | EventName::UnexpectedPersonDetected
    )
}

impl FaceEvent {
    /// The draft the queue numbers, or `invalid-event`.
    pub fn into_draft(self) -> CommandResult<EventDraft> {
        let invalid = |why: &str| CommandError::new("invalid-event", why.to_owned());
        if !is_camera_event(self.event) || self.source != Source::Camera {
            return Err(invalid("not a camera event"));
        }
        let started_at_ms =
            parse_rfc3339_ms(&self.started_at).ok_or_else(|| invalid("bad started_at"))?;
        if !self.confidence.is_finite() {
            return Err(invalid("bad confidence"));
        }
        let details = Value::Object(self.details);
        if details.to_string().len() > MAX_DETAILS_BYTES {
            return Err(invalid("details too large"));
        }
        let mut draft = EventDraft::new(self.event, Source::Camera, started_at_ms)
            .confidence(self.confidence)
            .details(details);
        if let Some(duration_ms) = self.duration_ms {
            draft = draft.duration_ms(duration_ms);
        }
        Ok(draft)
    }
}

/// `2026-10-12T05:01:02.120Z` (or with a `±HH:MM` offset) to milliseconds since the Unix epoch.
/// The inverse of `hv_event_queue::rfc3339_ms`.
pub fn parse_rfc3339_ms(text: &str) -> Option<i64> {
    let bytes = text.as_bytes();
    let digits = |from: usize, count: usize| -> Option<i64> {
        let slice = bytes.get(from..from + count)?;
        slice
            .iter()
            .all(u8::is_ascii_digit)
            .then(|| slice.iter().fold(0, |n, d| n * 10 + i64::from(d - b'0')))
    };
    let punct = |at: usize, expected: u8| (bytes.get(at) == Some(&expected)).then_some(());

    let year = digits(0, 4)?;
    punct(4, b'-')?;
    let month = digits(5, 2)?;
    punct(7, b'-')?;
    let day = digits(8, 2)?;
    punct(10, b'T')?;
    let hour = digits(11, 2)?;
    punct(13, b':')?;
    let minute = digits(14, 2)?;
    punct(16, b':')?;
    let second = digits(17, 2)?;
    let mut at = 19;

    let mut millis = 0;
    if bytes.get(at) == Some(&b'.') {
        at += 1;
        let start = at;
        while bytes.get(at).is_some_and(u8::is_ascii_digit) {
            at += 1;
        }
        let fraction = &bytes[start..at];
        if fraction.is_empty() || fraction.len() > 9 {
            return None;
        }
        // Milliseconds are the first three digits.
        for index in 0..3 {
            millis = millis * 10 + fraction.get(index).map_or(0, |d| i64::from(d - b'0'));
        }
    }

    let offset_minutes = match bytes.get(at)? {
        b'Z' => {
            at += 1;
            0
        }
        sign @ (b'+' | b'-') => {
            let hours = digits(at + 1, 2)?;
            punct(at + 3, b':')?;
            let minutes = digits(at + 4, 2)?;
            at += 6;
            if hours > 23 || minutes > 59 {
                return None;
            }
            let total = hours * 60 + minutes;
            if *sign == b'-' { -total } else { total }
        }
        _ => return None,
    };
    if at != bytes.len() {
        return None;
    }

    if !(1..=12).contains(&month) || hour > 23 || minute > 59 || second > 59 {
        return None;
    }
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days_in_month = match month {
        2 if leap => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    };
    if !(1..=days_in_month).contains(&day) {
        return None;
    }
    let seconds = days_from_civil(year, month, day) * 86_400 + hour * 3600 + minute * 60 + second
        - offset_minutes * 60;
    Some(seconds * 1000 + millis)
}

/// Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant's algorithm).
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let year_of_era = year - era * 400;
    let month_index = (month + 9) % 12;
    let day_of_year = (153 * month_index + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

/// What the app found before the monitor started, as the monitor takes it:
/// `("webview_environment", Some("WEBVIEW2_…"))` per override and `("debugger_attached", None)`.
pub fn startup_integrity(
    webview_variables: &[String],
    debugger_present: bool,
) -> Vec<(String, Option<String>)> {
    let mut findings: Vec<(String, Option<String>)> = webview_variables
        .iter()
        .map(|name| ("webview_environment".to_owned(), Some(name.clone())))
        .collect();
    if debugger_present {
        findings.push(("debugger_attached".to_owned(), None));
    }
    findings
}

/// The camera or microphone the webview reports as in use: its label, trimmed and bounded. An
/// empty label (WebView2 hid it) means the device is in use but unnamed.
pub fn device_label(reported: Option<&str>) -> CommandResult<Option<String>> {
    let Some(label) = reported else {
        return Ok(None);
    };
    if label.chars().any(char::is_control) {
        return Err(CommandError::new(
            "invalid-device",
            "control characters".to_owned(),
        ));
    }
    let label = label.trim();
    if label.chars().count() > MAX_LABEL_CHARS {
        return Err(CommandError::new(
            "invalid-device",
            "label too long".to_owned(),
        ));
    }
    Ok(Some(label.to_owned()))
}

/// What the heartbeat reports, kept current by the webview (camera, mic), the screen recorder
/// and the monitor (displays).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatusSnapshot {
    pub camera_on: bool,
    pub mic_on: bool,
    pub screen_capturing: bool,
    pub displays: u32,
    /// `connected`, `disconnected` or `not_required` (the third-eye link is SP-10's).
    pub third_eye: &'static str,
}

impl Default for StatusSnapshot {
    fn default() -> Self {
        Self {
            camera_on: false,
            mic_on: false,
            screen_capturing: false,
            displays: 1,
            third_eye: "not_required",
        }
    }
}

/// The heartbeat body's device fields (`proctoring.md`).
pub fn heartbeat_status(snapshot: &StatusSnapshot) -> DeviceStatus {
    let on_off = |on| if on { "on" } else { "off" }.to_owned();
    DeviceStatus {
        camera: on_off(snapshot.camera_on),
        mic: on_off(snapshot.mic_on),
        screen: if snapshot.screen_capturing {
            "capturing"
        } else {
            "stopped"
        }
        .to_owned(),
        third_eye: snapshot.third_eye.to_owned(),
        displays: snapshot.displays,
        cpu_percent: None,
        vision_fps: None,
    }
}

#[cfg(test)]
mod tests {
    use hv_event_queue::rfc3339_ms;
    use serde_json::json;

    use super::*;

    fn face(value: Value) -> CommandResult<EventDraft> {
        serde_json::from_value::<FaceEvent>(value)
            .expect("shape")
            .into_draft()
    }

    fn absent() -> Value {
        json!({
            "event": "FACE_ABSENT", "source": "camera",
            "started_at": "2026-10-12T05:01:02.120Z",
            "duration_ms": 5000, "confidence": 0.9, "evidence": [],
            "details": { "phase": "started", "level": "warning", "frames": 40 }
        })
    }

    #[test]
    fn a_face_event_becomes_a_draft() {
        let draft = face(absent()).expect("valid");
        assert_eq!(draft.event, EventName::FaceAbsent);
        assert_eq!(draft.source, Source::Camera);
        assert_eq!(rfc3339_ms(draft.started_at_ms), "2026-10-12T05:01:02.120Z");
        assert_eq!(draft.duration_ms, Some(5000));
        assert!((draft.confidence - 0.9).abs() < f64::EPSILON);
        assert!(draft.evidence.is_empty());
        assert_eq!(draft.details["phase"], "started");
        assert_eq!(draft.details["frames"], 40);
    }

    #[test]
    fn a_missing_duration_and_confidence_take_the_defaults() {
        let draft = face(json!({
            "event": "MULTIPLE_FACES", "source": "camera",
            "started_at": "2026-10-12T05:01:02Z"
        }))
        .expect("valid");
        assert_eq!(draft.duration_ms, None);
        assert!((draft.confidence - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn the_webview_cannot_raise_native_events() {
        for event in [
            "BLOCKED_PROCESS_DETECTED",
            "SCREEN_CAPTURE_STOPPED",
            "VM_DETECTED",
        ] {
            let mut value = absent();
            value["event"] = json!(event);
            assert_eq!(face(value).unwrap_err().code, "invalid-event", "{event}");
        }
        let mut value = absent();
        value["source"] = json!("native");
        assert_eq!(face(value).unwrap_err().code, "invalid-event");
    }

    #[test]
    fn unknown_event_names_do_not_parse() {
        let mut value = absent();
        value["event"] = json!("KEY_PRESSED");
        assert!(serde_json::from_value::<FaceEvent>(value).is_err());
    }

    #[test]
    fn bad_times_and_oversized_details_are_refused() {
        for started_at in [
            "",
            "yesterday",
            "2026-13-01T00:00:00Z",
            "2026-02-30T00:00:00Z",
        ] {
            let mut value = absent();
            value["started_at"] = json!(started_at);
            assert_eq!(
                face(value).unwrap_err().code,
                "invalid-event",
                "{started_at}"
            );
        }
        let mut value = absent();
        value["details"] = json!({ "blob": "x".repeat(MAX_DETAILS_BYTES) });
        assert_eq!(face(value).unwrap_err().code, "invalid-event");
    }

    #[test]
    fn timestamps_round_trip_with_the_queues_formatter() {
        for ms in [
            0,
            1,
            951_782_400_000,   // 2000-02-29
            1_760_245_400_123, // 2025-10
            1_791_000_000_999,
            4_102_444_799_000, // 2099-12-31T23:59:59
        ] {
            assert_eq!(parse_rfc3339_ms(&rfc3339_ms(ms)), Some(ms), "{ms}");
        }
    }

    #[test]
    fn offsets_fractions_and_garbage() {
        assert_eq!(parse_rfc3339_ms("1970-01-01T00:00:00Z"), Some(0));
        assert_eq!(parse_rfc3339_ms("1970-01-01T01:00:00+01:00"), Some(0));
        assert_eq!(parse_rfc3339_ms("1969-12-31T19:00:00-05:00"), Some(0));
        assert_eq!(parse_rfc3339_ms("1970-01-01T00:00:00.5Z"), Some(500));
        assert_eq!(parse_rfc3339_ms("1970-01-01T00:00:00.123456Z"), Some(123));
        for bad in [
            "1970-01-01T00:00:00",
            "1970-01-01 00:00:00Z",
            "1970-01-01T00:00:00.Z",
            "1970-01-01T24:00:00Z",
            "1970-01-01T00:00:00Zjunk",
            "1970-1-1T00:00:00Z",
            "1900-02-29T00:00:00Z",
        ] {
            assert_eq!(parse_rfc3339_ms(bad), None, "{bad}");
        }
    }

    #[test]
    fn startup_findings_become_monitor_integrity_inputs() {
        let findings = startup_integrity(&["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER".to_owned()], true);
        assert_eq!(
            findings,
            vec![
                (
                    "webview_environment".to_owned(),
                    Some("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER".to_owned())
                ),
                ("debugger_attached".to_owned(), None),
            ]
        );
        assert!(startup_integrity(&[], false).is_empty());
    }

    #[test]
    fn device_labels_are_trimmed_and_bounded() {
        assert_eq!(device_label(None).expect("ok"), None);
        assert_eq!(
            device_label(Some("  Integrated Camera ")).expect("ok"),
            Some("Integrated Camera".to_owned())
        );
        assert_eq!(device_label(Some("")).expect("ok"), Some(String::new()));
        assert_eq!(
            device_label(Some("a\nb")).unwrap_err().code,
            "invalid-device"
        );
        assert_eq!(
            device_label(Some(&"x".repeat(MAX_LABEL_CHARS + 1)))
                .unwrap_err()
                .code,
            "invalid-device"
        );
    }

    #[test]
    fn the_heartbeat_reports_the_apps_state() {
        let status = heartbeat_status(&StatusSnapshot {
            camera_on: true,
            mic_on: false,
            screen_capturing: true,
            displays: 2,
            third_eye: "connected",
        });
        assert_eq!(status.camera, "on");
        assert_eq!(status.mic, "off");
        assert_eq!(status.screen, "capturing");
        assert_eq!(status.third_eye, "connected");
        assert_eq!(status.displays, 2);

        let idle = heartbeat_status(&StatusSnapshot::default());
        assert_eq!(
            (
                idle.camera.as_str(),
                idle.screen.as_str(),
                idle.third_eye.as_str()
            ),
            ("off", "stopped", "not_required")
        );
        assert_eq!(idle.displays, 1);
    }
}
