"""Words for what reports show: proctoring events in plain English and which of PRD §68's
sections each belongs to. Every event the catalogue knows is here (a test keeps them in step), so
a new event can't silently vanish from the proctoring report."""

from __future__ import annotations

EVENT_LABELS: dict[str, str] = {
    "FACE_ABSENT": "Face not visible",
    "MULTIPLE_FACES": "More than one face in view",
    "FACE_TOO_FAR": "Face too far from the camera",
    "FACE_TOO_CLOSE": "Face too close to the camera",
    "GAZE_DEVIATION": "Looked away from the screen",
    "CAMERA_OBSTRUCTED": "Camera covered or obstructed",
    "PHONE_DETECTED": "Phone seen in the camera",
    "UNEXPECTED_PERSON_DETECTED": "Another person in view",
    "CAMERA_DISCONNECTED": "Camera disconnected",
    "MIC_DISCONNECTED": "Microphone disconnected",
    "SCREEN_CAPTURE_STOPPED": "Screen capture stopped",
    "DEVICE_CHANGE": "Camera or microphone changed",
    "APPLICATION_FOCUS_CHANGE": "Switched to another application",
    "WINDOW_MINIMIZED": "Interview window minimised",
    "UNEXPECTED_WINDOW": "Another window appeared on top",
    "BLOCKED_PROCESS_DETECTED": "Blocked application running",
    "EXTERNAL_DISPLAY_CHANGE": "Display connected or disconnected",
    "CAPTURE_EXCLUDED_WINDOW": "A window hidden from screen capture",
    "REMOTE_SESSION_DETECTED": "Remote session detected",
    "VIRTUAL_DEVICE_DETECTED": "Virtual camera or microphone",
    "VM_DETECTED": "Virtual machine detected",
    "CLIENT_INTEGRITY_WARNING": "Interview app integrity warning",
    "ADDITIONAL_SPEAKER_DETECTED": "Another voice heard",
    "CAMERA_RECONNECTED": "Camera reconnected",
    "MIC_RECONNECTED": "Microphone reconnected",
    "SESSION_INTERRUPTED": "Session interrupted",
    "SESSION_RESUMED": "Session resumed",
    "EDITOR_PASTE": "Pasted into the code editor",
    "EDITOR_FOCUS_CHANGE": "Left the code editor",
    "THIRD_EYE_DISCONNECTED": "Third-eye camera disconnected",
    "THIRD_EYE_RECONNECTED": "Third-eye camera reconnected",
    "TELEMETRY_GAP": "Monitoring data missing",
}

# PRD §68's sections an event belongs to; every event is in exactly one.
EVENT_SECTIONS: dict[str, tuple[str, ...]] = {
    "camera_status": ("CAMERA_DISCONNECTED", "CAMERA_RECONNECTED"),
    "microphone_status": ("MIC_DISCONNECTED", "MIC_RECONNECTED", "ADDITIONAL_SPEAKER_DETECTED"),
    "screen_status": ("SCREEN_CAPTURE_STOPPED", "EXTERNAL_DISPLAY_CHANGE"),
    "third_eye_status": ("THIRD_EYE_DISCONNECTED", "THIRD_EYE_RECONNECTED"),
    "application_events": (
        "APPLICATION_FOCUS_CHANGE",
        "WINDOW_MINIMIZED",
        "UNEXPECTED_WINDOW",
        "EDITOR_FOCUS_CHANGE",
        "EDITOR_PASTE",
    ),
    "process_events": (
        "BLOCKED_PROCESS_DETECTED",
        "REMOTE_SESSION_DETECTED",
        "VM_DETECTED",
        "VIRTUAL_DEVICE_DETECTED",
        "CAPTURE_EXCLUDED_WINDOW",
        "CLIENT_INTEGRITY_WARNING",
        "DEVICE_CHANGE",
    ),
    "face_events": (
        "FACE_ABSENT",
        "MULTIPLE_FACES",
        "FACE_TOO_FAR",
        "FACE_TOO_CLOSE",
        "CAMERA_OBSTRUCTED",
        "UNEXPECTED_PERSON_DETECTED",
    ),
    "gaze_events": ("GAZE_DEVIATION",),
    "object_events": ("PHONE_DETECTED",),
    "session_summary": ("SESSION_INTERRUPTED", "SESSION_RESUMED", "TELEMETRY_GAP"),
}
SECTION_OF_EVENT = {
    event: section for section, events in EVENT_SECTIONS.items() for event in events
}

REVIEW_LABELS = {
    "pending": "Not yet reviewed",
    "confirmed": "Confirmed by a reviewer",
    "false_positive": "Marked a false positive",
    "not_relevant": "Marked not relevant",
}
SEVERITY_LABELS = {"INFO": "Information", "WARNING": "Warning", "CRITICAL": "Critical"}
SOURCE_LABELS = {
    "camera": "Camera",
    "third_eye": "Third-eye camera",
    "screen": "Screen",
    "native": "Interview app",
    "editor": "Code editor",
    "audio": "Microphone",
    "interview": "Interview",
}
STATUS_LABELS = {
    "scheduled": "Scheduled",
    "invited": "Invited",
    "in_progress": "In progress",
    "interrupted": "Interrupted",
    "completed": "Completed",
    "evaluating": "Being evaluated",
    "evaluated": "Evaluated",
    "expired": "Expired",
    "cancelled": "Cancelled",
    "abandoned": "Abandoned",
}
HIRING_LABELS = {
    "under_review": "Under review",
    "shortlisted": "Shortlisted",
    "interview_invited": "Interview invited",
    "interview_started": "Interview started",
    "interview_completed": "Interview completed",
    "additional_review": "Additional review",
    "selected": "Selected",
    "rejected": "Rejected",
    "on_hold": "On hold",
}
RECOMMENDATION_LABELS = {
    "strong_hire": "Strong yes",
    "hire": "Yes",
    "hold": "Undecided",
    "no_hire": "No",
    "strong_no_hire": "Strong no",
}
DIMENSION_LABELS = {
    "relevance": "Relevance",
    "correctness": "Correctness",
    "completeness": "Completeness",
    "technical_depth": "Technical depth",
    "reasoning": "Reasoning",
    "clarity": "Clarity",
    "communication": "Communication",
    "evidence": "Evidence",
}


def event_label(event: str) -> str:
    return EVENT_LABELS.get(event, event.replace("_", " ").capitalize())
