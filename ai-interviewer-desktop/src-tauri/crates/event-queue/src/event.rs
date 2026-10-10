//! The event schema of `docs/api/contracts/proctoring.md` (PRD §67).

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Every event name the contract accepts, and nothing else: the server refuses a whole batch
/// with `422 unknown-event` when one name is unknown, so names are typed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EventName {
    // camera
    FaceAbsent,
    MultipleFaces,
    FaceTooFar,
    FaceTooClose,
    GazeDeviation,
    CameraObstructed,
    PhoneDetected,
    UnexpectedPersonDetected,
    // devices
    CameraDisconnected,
    MicDisconnected,
    ScreenCaptureStopped,
    // focus and processes
    ApplicationFocusChange,
    WindowMinimized,
    BlockedProcessDetected,
    ExternalDisplayChange,
    // environment
    CaptureExcludedWindow,
    RemoteSessionDetected,
    VirtualDeviceDetected,
    VmDetected,
    ClientIntegrityWarning,
    // audio
    AdditionalSpeakerDetected,
    // lifecycle
    CameraReconnected,
    MicReconnected,
    SessionInterrupted,
    SessionResumed,
    // editor
    EditorPaste,
    EditorFocusChange,
}

impl EventName {
    /// The name on the wire.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::FaceAbsent => "FACE_ABSENT",
            Self::MultipleFaces => "MULTIPLE_FACES",
            Self::FaceTooFar => "FACE_TOO_FAR",
            Self::FaceTooClose => "FACE_TOO_CLOSE",
            Self::GazeDeviation => "GAZE_DEVIATION",
            Self::CameraObstructed => "CAMERA_OBSTRUCTED",
            Self::PhoneDetected => "PHONE_DETECTED",
            Self::UnexpectedPersonDetected => "UNEXPECTED_PERSON_DETECTED",
            Self::CameraDisconnected => "CAMERA_DISCONNECTED",
            Self::MicDisconnected => "MIC_DISCONNECTED",
            Self::ScreenCaptureStopped => "SCREEN_CAPTURE_STOPPED",
            Self::ApplicationFocusChange => "APPLICATION_FOCUS_CHANGE",
            Self::WindowMinimized => "WINDOW_MINIMIZED",
            Self::BlockedProcessDetected => "BLOCKED_PROCESS_DETECTED",
            Self::ExternalDisplayChange => "EXTERNAL_DISPLAY_CHANGE",
            Self::CaptureExcludedWindow => "CAPTURE_EXCLUDED_WINDOW",
            Self::RemoteSessionDetected => "REMOTE_SESSION_DETECTED",
            Self::VirtualDeviceDetected => "VIRTUAL_DEVICE_DETECTED",
            Self::VmDetected => "VM_DETECTED",
            Self::ClientIntegrityWarning => "CLIENT_INTEGRITY_WARNING",
            Self::AdditionalSpeakerDetected => "ADDITIONAL_SPEAKER_DETECTED",
            Self::CameraReconnected => "CAMERA_RECONNECTED",
            Self::MicReconnected => "MIC_RECONNECTED",
            Self::SessionInterrupted => "SESSION_INTERRUPTED",
            Self::SessionResumed => "SESSION_RESUMED",
            Self::EditorPaste => "EDITOR_PASTE",
            Self::EditorFocusChange => "EDITOR_FOCUS_CHANGE",
        }
    }
}

/// Where an event comes from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    Camera,
    ThirdEye,
    Screen,
    Native,
    Editor,
    Audio,
    Interview,
}

/// A piece of evidence an event points at (an uploaded snapshot, a segment).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Evidence {
    #[serde(rename = "type")]
    pub kind: String,
    pub blob_path: String,
}

/// An event before the queue gives it a sequence number.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventDraft {
    pub event: EventName,
    pub source: Source,
    /// Server time, milliseconds since the Unix epoch.
    pub started_at_ms: i64,
    pub duration_ms: Option<u64>,
    pub confidence: f64,
    pub evidence: Vec<Evidence>,
    pub details: Map<String, Value>,
}

impl EventDraft {
    /// A draft with full confidence, no duration, no evidence and no details.
    pub fn new(event: EventName, source: Source, started_at_ms: i64) -> Self {
        Self {
            event,
            source,
            started_at_ms,
            duration_ms: None,
            confidence: 1.0,
            evidence: Vec::new(),
            details: Map::new(),
        }
    }

    #[must_use]
    pub fn duration_ms(mut self, duration_ms: u64) -> Self {
        self.duration_ms = Some(duration_ms);
        self
    }

    #[must_use]
    pub fn confidence(mut self, confidence: f64) -> Self {
        self.confidence = confidence.clamp(0.0, 1.0);
        self
    }

    /// Sets the details from a JSON object (anything else is ignored).
    #[must_use]
    pub fn details(mut self, details: Value) -> Self {
        if let Value::Object(map) = details {
            self.details = map;
        }
        self
    }

    /// The event with its sequence number.
    pub fn into_event(self, seq: u64) -> ProctorEvent {
        ProctorEvent {
            seq,
            event: self.event,
            source: self.source,
            started_at: rfc3339_ms(self.started_at_ms),
            duration_ms: self.duration_ms,
            confidence: self.confidence,
            evidence: self.evidence,
            details: self.details,
        }
    }
}

/// One event as `POST /proctoring/events` carries it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProctorEvent {
    pub seq: u64,
    pub event: EventName,
    pub source: Source,
    /// Server time, RFC 3339 with milliseconds (`2026-10-12T05:01:02.120Z`).
    pub started_at: String,
    pub duration_ms: Option<u64>,
    pub confidence: f64,
    #[serde(default)]
    pub evidence: Vec<Evidence>,
    #[serde(default)]
    pub details: Map<String, Value>,
}

/// Milliseconds since the Unix epoch as RFC 3339 UTC with milliseconds.
pub fn rfc3339_ms(ms: i64) -> String {
    let seconds = ms.div_euclid(1000);
    let millis = ms.rem_euclid(1000);
    let days = seconds.div_euclid(86_400);
    let of_day = seconds.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{millis:03}Z",
        of_day / 3600,
        of_day % 3600 / 60,
        of_day % 60
    )
}

/// Days since 1970-01-01 to a proleptic Gregorian date (Howard Hinnant's algorithm).
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    (year, month, day)
}
