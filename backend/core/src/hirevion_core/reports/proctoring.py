"""The proctoring report (PRD §68): fourteen sections of what the system saw.

It deliberately has no single "cheating score". Each event is shown with its source, how long it
lasted, how confident the detector was, why it got its severity and what a reviewer made of it;
what a reviewer dismissed stays in the report, marked as dismissed. Evidence appears as
references only: the pictures and recordings are shown in the review workspace, where each
viewing is audited."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from hirevion_core.models import ProctorEvent
from hirevion_core.proctoring import observed
from hirevion_core.reports import blocks as b
from hirevion_core.reports.blocks import Block, Document, Section
from hirevion_core.reports.data import InterviewData
from hirevion_core.reports.labels import (
    EVENT_SECTIONS,
    REVIEW_LABELS,
    SEVERITY_LABELS,
    SOURCE_LABELS,
    event_label,
)
from hirevion_core.reports.timeline import track_label

SECTION_KEYS = (
    "session_summary",
    "device_checks",
    "camera_status",
    "microphone_status",
    "screen_status",
    "third_eye_status",
    "application_events",
    "process_events",
    "face_events",
    "gaze_events",
    "object_events",
    "timeline",
    "evidence",
    "reviewer_notes",
)
STATE_LABELS = {"up": "Working", "down": "Down", "unknown": "Not observed"}
NO_SCORE = (
    "This report has no single score for cheating or honesty, on purpose. It lists what the "
    "system saw, how sure each detector was and what a reviewer made of it. Signals are not "
    "proof: people decide what they mean."
)
EVENT_COLUMNS = ["Time", "What", "Severity", "Lasted", "Confidence", "Seen by", "Why", "Review"]


def explain(reasons: Iterable[str]) -> str:
    """The server's reasons for a severity, in words."""
    words: list[str] = []
    for reason in reasons:
        kind, _, value = reason.partition(":")
        if kind == "duration":
            seconds = int(value.removesuffix("ms") or 0) / 1000
            words.append(f"lasted {seconds:g} s")
        elif kind == "fixed":
            words.append(f"always {value.lower()}")
        elif kind == "category":
            words.append(f"blocked category: {value.replace('_', ' ')}")
        elif kind == "repeated":
            words.append(f"repeated {value}")
        elif kind == "check-off":
            words.append("not checked at this level")
        elif kind == "corroborated":
            words.append("backed by other events")
        else:
            words.append(reason.replace("_", " "))
    return "; ".join(words)


def _review_text(data: InterviewData, event: ProctorEvent) -> str:
    review = data.reviews.get(event.id)
    if review is None:
        return REVIEW_LABELS["pending"]
    return f"{REVIEW_LABELS[review.outcome]}: {review.reason}"


def event_row(data: InterviewData, event: ProctorEvent) -> list[str | None]:
    server = (event.details or {}).get("server") or {}
    return [
        b.clock(data.offset_ms(event.started_at)),
        event_label(event.event),
        SEVERITY_LABELS.get(event.severity, event.severity),
        f"{round(event.duration_ms / 1000)} s" if event.duration_ms else None,
        f"{float(event.confidence):.2f}" if event.confidence is not None else None,
        SOURCE_LABELS.get(event.source, event.source),
        explain(server.get("reasons") or []) or None,
        _review_text(data, event),
    ]


def _events_in(data: InterviewData, names: Sequence[str]) -> list[ProctorEvent]:
    return [event for event in data.events if event.event in names]


def _events_table(data: InterviewData, section: str, caption: str) -> Block:
    rows = [event_row(data, event) for event in _events_in(data, EVENT_SECTIONS[section])]
    return b.table(caption, EVENT_COLUMNS, rows)


def _recordings(data: InterviewData, *prefixes: str) -> list[tuple[str, str | None]]:
    rows: list[tuple[str, str | None]] = []
    for recording in data.recordings:
        if recording.track.startswith(prefixes):
            length = b.clock(recording.duration_ms) if recording.duration_ms is not None else None
            rows.append(
                (
                    f"{track_label(recording.track)} recording",
                    f"{recording.status.replace('-', ' ')}"
                    + (f", {length} long" if length else "")
                    + (f", {len(recording.gaps)} gap(s)" if recording.gaps else ""),
                )
            )
    return rows


def _device_state(data: InterviewData, channel: str) -> tuple[str, str | None]:
    if data.proctor is None:
        return STATE_LABELS["unknown"], None
    state = observed.state_of(data.proctor.observed, channel)
    reported = (data.proctor.last_status or {}).get(channel)
    return STATE_LABELS[state], str(reported) if reported is not None else None


def _device_section(
    data: InterviewData,
    key: str,
    title: str,
    channel: str,
    event_section: str,
    recordings: tuple[str, ...],
    extra: Sequence[tuple[str, str | None]] = (),
) -> Section:
    seen, reported = _device_state(data, channel)
    rows: list[tuple[str, str | None]] = [
        ("Seen by the server", seen),
        ("Reported by the interview app", reported),
        *extra,
        *_recordings(data, *recordings),
    ]
    return b.section(
        key,
        title,
        [b.facts(rows), _events_table(data, event_section, f"{title}: events")],
    )


def session_summary(data: InterviewData) -> Section:
    proctor = data.proctor
    counts: dict[str, dict[str, int]] = {
        severity: {"total": 0, "confirmed": 0, "false_positive": 0, "not_relevant": 0, "pending": 0}
        for severity in SEVERITY_LABELS
    }
    for event in data.events:
        row = counts.setdefault(
            event.severity,
            {"total": 0, "confirmed": 0, "false_positive": 0, "not_relevant": 0, "pending": 0},
        )
        row["total"] += 1
        review = data.reviews.get(event.id)
        row[review.outcome if review else "pending"] += 1
    content: list[Block] = [b.notice(NO_SCORE)]
    if proctor is None:
        content.append(
            b.facts(
                [
                    (
                        "Proctoring level",
                        str((data.interview.policy or {}).get("proctoring_level") or ""),
                    )
                ]
            )
        )
        return b.section(
            "session_summary",
            "Session summary",
            content,
            empty=True,
            note="No proctoring session was opened for this interview.",
        )
    tz = data.timezone
    policy = proctor.policy or {}
    gaps = len(_events_in(data, ("TELEMETRY_GAP",)))
    interruptions = len(_events_in(data, ("SESSION_INTERRUPTED",)))
    content.append(
        b.facts(
            [
                ("Proctoring level", proctor.level),
                ("Policy version", str(proctor.policy_version)),
                ("Session", proctor.status),
                ("Opened", b.when(proctor.opened_at, tz)),
                ("Closed", b.when(proctor.closed_at, tz)),
                ("Heartbeats received", str(proctor.heartbeats)),
                ("Last heartbeat", b.when(proctor.last_heartbeat_at, tz)),
                ("Checks switched on", ", ".join(policy.get("checks", [])) or "None"),
                ("Accommodations", ", ".join(policy.get("accommodations", [])) or "None"),
                ("Interview app version", proctor.app_version),
                ("Times monitoring data was missing", str(gaps)),
                ("Times the session was interrupted", str(interruptions)),
                ("Events recorded", str(len(data.events))),
            ]
        )
    )
    content.append(
        b.table(
            "Events by severity and review",
            [
                "Severity",
                "Total",
                "Confirmed",
                "False positive",
                "Not relevant",
                "Not yet reviewed",
            ],
            [
                [
                    SEVERITY_LABELS[severity],
                    str(row["total"]),
                    str(row["confirmed"]),
                    str(row["false_positive"]),
                    str(row["not_relevant"]),
                    str(row["pending"]),
                ]
                for severity, row in counts.items()
            ],
        )
    )
    return b.section("session_summary", "Session summary", content)


def device_checks(data: InterviewData) -> Section:
    check = data.system_check
    if check is None:
        return b.section(
            "device_checks",
            "Device checks",
            [],
            note="The candidate's system check was not recorded.",
        )
    return b.section(
        "device_checks",
        "Device checks",
        [
            b.facts(
                [
                    ("Checked", b.when(check.created_at, data.timezone)),
                    ("Interview app version", check.app_version),
                    ("Operating system", check.os),
                    ("Required checks passed", "Yes" if check.passed else "No"),
                    ("Required checks that failed", ", ".join(check.failed_mandatory) or "None"),
                ]
            ),
            b.table(
                "Checks the interview app ran before the interview",
                ["Check", "Result", "Detail"],
                [
                    [
                        b.label(str(item.get("check", ""))),
                        b.label(str(item.get("status", ""))),
                        str(item["value"]) if item.get("value") is not None else None,
                    ]
                    for item in check.results
                ],
            ),
        ],
    )


def camera_status(data: InterviewData) -> Section:
    return _device_section(
        data, "camera_status", "Camera status", "camera", "camera_status", ("camera",)
    )


def microphone_status(data: InterviewData) -> Section:
    return _device_section(
        data,
        "microphone_status",
        "Microphone status",
        "mic",
        "microphone_status",
        ("mic", "conversation-audio"),
    )


def screen_status(data: InterviewData) -> Section:
    displays = (data.proctor.last_status or {}).get("displays") if data.proctor else None
    return _device_section(
        data,
        "screen_status",
        "Screen status",
        "screen",
        "screen_status",
        ("screen-",),
        extra=[("Displays connected", str(displays) if displays is not None else None)],
    )


def third_eye_status(data: InterviewData) -> Section:
    policy = data.interview.policy or {}
    return _device_section(
        data,
        "third_eye_status",
        "Third-eye status",
        "third_eye",
        "third_eye_status",
        ("third-eye",),
        extra=[("Third eye in this interview's policy", str(policy.get("third_eye") or ""))],
    )


def _events_section(data: InterviewData, key: str, title: str, empty: str) -> Section:
    rows = [event_row(data, event) for event in _events_in(data, EVENT_SECTIONS[key])]
    return b.section(
        key,
        title,
        [b.table(f"{title}, in order", EVENT_COLUMNS, rows)],
        note=None if rows else empty,
    )


def application_events(data: InterviewData) -> Section:
    return _events_section(
        data,
        "application_events",
        "Application events",
        "The candidate stayed in the interview application throughout.",
    )


def process_events(data: InterviewData) -> Section:
    return _events_section(
        data,
        "process_events",
        "Process events",
        "No blocked applications or unusual processes were seen.",
    )


def face_events(data: InterviewData) -> Section:
    return _events_section(
        data, "face_events", "Face events", "The candidate's face was in view throughout."
    )


def gaze_events(data: InterviewData) -> Section:
    return _events_section(
        data,
        "gaze_events",
        "Gaze events",
        "No looking away from the screen was recorded. Gaze is only ever a signal.",
    )


def object_events(data: InterviewData) -> Section:
    return _events_section(
        data, "object_events", "Object events", "No phones or other objects were seen."
    )


def timeline(data: InterviewData) -> Section:
    rows = [event_row(data, event) for event in data.events]
    return b.section(
        "timeline",
        "Timeline",
        [
            b.table(
                "Every event, in order (times are from the start of the interview)",
                EVENT_COLUMNS,
                rows,
            )
        ],
        note=None if rows else "No events were recorded.",
    )


def _evidence_detail(item: Any) -> str | None:
    ref = item.ref or {}
    if item.kind == "process_metadata":
        return str(ref.get("name") or ref.get("process") or "Process details") or None
    if item.kind == "transcript_segment":
        return "Transcript turns around the event"
    if item.bytes:
        return f"{round(item.bytes / 1024)} KB"
    return None


def evidence(data: InterviewData) -> Section:
    events = {event.id: event for event in data.events}
    rows: list[list[str | None]] = []
    for item in data.evidence:
        event = events.get(item.proctor_event_id) if item.proctor_event_id else None
        window = None
        if item.window_start is not None and item.window_end is not None:
            start = b.clock(data.offset_ms(item.window_start))
            end = b.clock(data.offset_ms(item.window_end))
            window = f"{start} to {end}"
        rows.append(
            [
                b.label(item.kind),
                event_label(event.event) if event else None,
                window,
                _evidence_detail(item),
                b.label(item.origin),
                item.sha256[:12] if item.sha256 else None,
            ]
        )
    return b.section(
        "evidence",
        "Evidence",
        [
            b.table(
                "Evidence kept for the events",
                ["Kind", "For event", "Window", "Detail", "Collected by", "SHA-256"],
                rows,
            ),
            b.text(
                "Pictures and recordings are not in this report. Open them in the review "
                "workspace, where each viewing is recorded.",
                muted=True,
            ),
        ],
        note=None if rows else "No evidence was kept.",
    )


def reviewer_notes(data: InterviewData) -> Section:
    events = {event.id: event for event in data.events}
    tz = data.timezone
    reviews = [
        [
            b.when(review.created_at, tz),
            data.person(review.reviewer_id),
            event_label(events[review.proctor_event_id].event)
            if review.proctor_event_id in events
            else None,
            REVIEW_LABELS[review.outcome],
            review.reason,
        ]
        for review in data.all_reviews
    ]
    notes = [
        [
            b.when(note.created_at, tz),
            data.person(note.author_id),
            b.clock(note.at_ms) if note.at_ms is not None else None,
            note.body,
        ]
        for note in data.notes
    ]
    return b.section(
        "reviewer_notes",
        "Reviewer notes",
        [
            b.table(
                "Decisions about events",
                ["When", "Reviewer", "Event", "Decision", "Reason"],
                reviews,
            ),
            b.table("Notes about the interview", ["When", "By", "At", "Note"], notes),
        ],
        note=None if reviews or notes else "No reviewer has added a decision or a note yet.",
    )


def proctoring_report(data: InterviewData, *, generated_at: datetime | None = None) -> Document:
    sections = [
        session_summary(data),
        device_checks(data),
        camera_status(data),
        microphone_status(data),
        screen_status(data),
        third_eye_status(data),
        application_events(data),
        process_events(data),
        face_events(data),
        gaze_events(data),
        object_events(data),
        timeline(data),
        evidence(data),
        reviewer_notes(data),
    ]
    interview = data.interview
    return b.document(
        "proctoring",
        "Proctoring report",
        f"IV-{interview.number:04d} · {data.candidate.name} · {data.job.title}",
        sections,
        subject={
            "interview_id": str(interview.id),
            "candidate_id": str(data.candidate.id),
            "candidate_name": data.candidate.name,
            "job_title": data.job.title,
        },
        generated_at=generated_at,
    )
