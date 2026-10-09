"""What the candidate is told before the interview (PRD §29, §30, §83): the instructions, the
mandatory system checks, the itemised notice to consent to, the accommodations and the answer
mode, all derived from the interview's pinned policy and the approved accommodations.

`NOTICE_VERSION` names the notice's wording; change it whenever `NOTICE_TEXT` changes, so a
consent given to older wording is refused (`notice-outdated`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Invalid
from hirevion_core.models import Accommodation, Interview, Organization, OrganizationSettings

NOTICE_VERSION = "2026-10-09"
# PRD §29's eleven checks, plus the desktop contract's two.
CHECK_NAMES = (
    "camera",
    "microphone",
    "speaker",
    "screen_capture",
    "network",
    "cpu",
    "memory",
    "disk",
    "displays",
    "privacy",
    "third_eye",
    "media_foundation",
    "webview2",
)
CHECK_STATUSES = ("pass", "warn", "fail", "skipped")
# PRD §83's ten purposes.
CONSENT_PURPOSES = (
    "camera",
    "microphone",
    "screen",
    "audio",
    "video",
    "third_eye",
    "transcript",
    "coding_activity",
    "system_telemetry",
    "proctoring_events",
)
ACCOMMODATION_KINDS = (
    "extended_time",
    "text_answers",
    "breaks",
    "assistive_technology",
    "relaxed_gaze",
    "third_eye_waiver",
)
EXTENDED_TIME_FACTOR = 1.5
# PRD §30's instructions, used until the organisation writes its own.
DEFAULT_INSTRUCTIONS = (
    "Find a quiet, well-lit room and close unnecessary applications.",
    "Keep your camera and microphone on, and your face visible, throughout.",
    "Keep the interview application in focus and in full screen.",
    "Don't use other applications, devices, notes or other people's help.",
    "If the interview uses a phone as a third camera, follow its placement guide.",
    "Speak your answers aloud; you can ask the interviewer to repeat a question.",
)
NOTICE_TEXT = {
    "camera": "Your camera is on throughout the interview, to confirm it's you and that you're "
    "working alone.",
    "microphone": "Your microphone is on throughout, so you can answer aloud and so background "
    "voices can be noticed.",
    "screen": "Your screen is captured while the interview runs.",
    "audio": "The interview's audio is recorded.",
    "video": "Your camera video is recorded.",
    "third_eye": "A phone you pair shows your desk and screen from the side, and its video is "
    "recorded.",
    "transcript": "Everything said in the interview, by you and the AI, is transcribed and kept "
    "with the interview.",
    "coding_activity": "Your code, runs and submissions in the editor are recorded.",
    "system_telemetry": "The app checks your system while it runs: focus, displays, and "
    "applications that aren't allowed. It never records keystrokes.",
    "proctoring_events": "Events that may break the interview's rules are recorded for the "
    "recruiting team to review; none of them decides anything on its own.",
}


@dataclass(frozen=True, slots=True)
class NoticeItem:
    purpose: str
    text: str
    required: bool


@dataclass(frozen=True, slots=True)
class Briefing:
    instructions: list[str]
    mandatory_checks: list[str]
    notice_version: str
    notice: list[NoticeItem]
    requested: list[str]
    approved: list[str]
    answer_mode: Literal["voice", "text"]
    third_eye: str
    support_email: str | None = None
    duration_minutes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def accommodations(policy: dict[str, Any]) -> set[str]:
    return {str(kind) for kind in policy.get("accommodations") or []}


def answer_mode(policy: dict[str, Any]) -> Literal["voice", "text"]:
    if "text_answers" in accommodations(policy):
        return "text"
    return "text" if policy.get("answer_mode") == "text" else "voice"


def third_eye_mode(policy: dict[str, Any]) -> str:
    mode = str(policy.get("third_eye") or "off")
    if mode == "required" and "third_eye_waiver" in accommodations(policy):
        return "optional"
    return mode


def mandatory_checks(policy: dict[str, Any]) -> list[str]:
    granted = accommodations(policy)
    checks = [str(c) for c in policy.get("mandatory_checks") or []]
    if "text_answers" in granted:
        checks = [c for c in checks if c != "microphone"]
    if third_eye_mode(policy) != "required":
        checks = [c for c in checks if c != "third_eye"]
    return checks


def duration_minutes(interview: Interview) -> float:
    factor = EXTENDED_TIME_FACTOR if "extended_time" in accommodations(interview.policy) else 1
    return interview.duration_minutes * factor


def notice_items(policy: dict[str, Any]) -> list[NoticeItem]:
    """The purposes this interview's policy collects, each required when the policy needs it."""
    recording = policy.get("recording") or {}
    level = str(policy.get("proctoring_level") or "standard")
    proctored = level != "off"
    voice = answer_mode(policy) == "voice"
    third_eye = third_eye_mode(policy)
    coding = bool((policy.get("coding") or {}).get("enabled"))
    wanted: list[tuple[str, bool]] = []
    if proctored or recording.get("camera"):
        wanted.append(("camera", True))
    wanted.append(("microphone", voice or bool(recording.get("audio"))))
    if recording.get("screen") or level in ("standard", "strict"):
        wanted.append(("screen", True))
    if recording.get("audio"):
        wanted.append(("audio", True))
    if recording.get("camera"):
        wanted.append(("video", True))
    if third_eye != "off":
        wanted.append(("third_eye", third_eye == "required"))
    wanted.append(("transcript", True))
    if coding:
        wanted.append(("coding_activity", True))
    if proctored:
        wanted.append(("system_telemetry", True))
        wanted.append(("proctoring_events", True))
    return [NoticeItem(p, NOTICE_TEXT[p], required) for p, required in wanted]


async def briefing(session: AsyncSession, interview: Interview) -> Briefing:
    settings = await session.scalar(
        select(OrganizationSettings.interview_briefing).where(
            OrganizationSettings.organization_id == interview.organization_id
        )
    )
    instructions = [
        str(line) for line in (settings or {}).get("instructions") or [] if str(line).strip()
    ] or list(DEFAULT_INSTRUCTIONS)
    support = await session.scalar(
        select(Organization.support_email).where(Organization.id == interview.organization_id)
    )
    requested: list[str] = []
    for row in await session.scalars(
        select(Accommodation)
        .where(Accommodation.interview_id == interview.id)
        .order_by(Accommodation.created_at)
    ):
        requested += [k for k in row.kinds if k not in requested]
    policy = interview.policy or {}
    return Briefing(
        instructions=instructions,
        mandatory_checks=mandatory_checks(policy),
        notice_version=NOTICE_VERSION,
        notice=notice_items(policy),
        requested=requested,
        approved=sorted(accommodations(policy)),
        answer_mode=answer_mode(policy),
        third_eye=third_eye_mode(policy),
        support_email=support,
        duration_minutes=round(duration_minutes(interview)),
    )


INSTRUCTIONS_MAX = 20
INSTRUCTION_LENGTH = 300
FAQ_MAX = 50


async def briefing_settings(session: AsyncSession) -> dict[str, Any]:
    """The organisation's instructions and FAQ (the session's tenant), as saved."""
    saved = await session.scalar(select(OrganizationSettings.interview_briefing))
    return {
        "instructions": [str(line) for line in (saved or {}).get("instructions") or []],
        "faq": [
            {"question": str(item.get("question", "")), "answer": str(item.get("answer", ""))}
            for item in (saved or {}).get("faq") or []
        ],
    }


async def save_briefing_settings(
    session: AsyncSession,
    actor: Actor,
    instructions: list[str],
    faq: list[dict[str, str]],
) -> dict[str, Any]:
    """Replaces the instructions (empty means the defaults) and the FAQ; audited."""
    lines = [" ".join(line.split())[:INSTRUCTION_LENGTH] for line in instructions]
    lines = [line for line in lines if line][:INSTRUCTIONS_MAX]
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in faq[:FAQ_MAX]:
        question = " ".join(str(item.get("question", "")).split())
        answer = str(item.get("answer", "")).strip()
        if not question or not answer:
            raise Invalid(
                "faq-incomplete", "Each FAQ entry needs a question and an answer", field="faq"
            )
        if question.casefold() in seen:
            raise Invalid("faq-duplicate", "Each FAQ question must be different", field="faq")
        seen.add(question.casefold())
        entries.append({"question": question, "answer": answer})
    row = await session.scalar(select(OrganizationSettings))
    if row is None:
        row = OrganizationSettings(organization_id=actor.organization_id)
        session.add(row)
    row.interview_briefing = {"instructions": lines, "faq": entries}
    row.updated_by = actor.user_id
    await session.flush()
    await record(
        session,
        actor,
        "organization.interview_briefing.changed",
        "organization",
        actor.organization_id,
        details={"instructions": len(lines), "faq": len(entries)},
    )
    return {"instructions": lines, "faq": entries}


@dataclass(frozen=True, slots=True)
class ResumePolicy:
    grace_seconds: int
    max_interruptions: int
    pause_timer: bool


def resume_policy(policy: dict[str, Any]) -> ResumePolicy:
    """The interview's resume policy, with its defaults only where a value is missing (a 0 grace
    or limit means none, as the scheduler's SQL reads it too)."""
    resume = (policy or {}).get("resume") or {}
    grace = resume.get("grace_seconds")
    limit = resume.get("max_interruptions")
    pause = resume.get("pause_timer")
    return ResumePolicy(
        grace_seconds=int(grace) if grace is not None else 300,
        max_interruptions=int(limit) if limit is not None else 3,
        pause_timer=bool(pause) if pause is not None else True,
    )
