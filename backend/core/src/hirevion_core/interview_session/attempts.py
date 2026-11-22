"""One attempt per interview (C8-9, product owner 2026-11-22).

An interview is taken once. A deliberate end (End Interview, closing the window) is final. After
a crash or a lost connection the candidate may rejoin once, within the policy's reconnect window
(`resume.grace_seconds`), and under a `same_device` policy only from the laptop that started it
(the session token's DPoP key). `attempt_of` is the one place that decides; the candidate's list,
the session-token route, the preparation routes and `Conductor.start` all ask it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from hirevion_core.interview_session.briefing import resume_policy
from hirevion_core.models import Interview, InterviewSession

Attempt = Literal["available", "not_open", "reconnect", "elsewhere", "used", "expired"]

TAKEN = frozenset({"completed", "evaluating", "evaluated", "abandoned"})
"""Statuses of an interview whose attempt was used: it can never be started again."""
RUNNING = frozenset({"in_progress", "interrupted"})


@dataclass(frozen=True, slots=True)
class AttemptView:
    state: Attempt
    reconnect_until: datetime | None = None
    """While interrupted: when the reconnect window closes."""


def window_end(interview: Interview) -> datetime:
    """When the interview can no longer be taken: the window's end, plus its duration once it
    has started (so one started late in its window can finish)."""
    if interview.status in RUNNING:
        return interview.expires_at + timedelta(minutes=interview.duration_minutes)
    return interview.expires_at


def attempt_of(
    interview: Interview, row: InterviewSession | None, *, jkt: str | None, now: datetime
) -> AttemptView:
    """What the candidate holding the DPoP key `jkt` may do with `interview` at `now`."""
    status = interview.status
    if status in TAKEN or status == "cancelled":
        return AttemptView("used")
    if status == "expired" or now >= window_end(interview):
        return AttemptView("expired")
    if status == "invited":
        return AttemptView("available" if now >= interview.starts_at else "not_open")
    if status not in RUNNING:
        return AttemptView("not_open")
    if row is None:
        # No checkpoint to judge by (the first start writes it with the status, so only a seeded
        # row lacks it): `Conductor.start` refuses such an interview itself.
        return AttemptView("reconnect")
    policy = resume_policy(interview.policy)
    if policy.same_device and row.device_jkt and jkt != row.device_jkt:
        return AttemptView("elsewhere")
    if status == "in_progress":
        return AttemptView("reconnect")
    interrupted = interview.interrupted_at or now
    until = interrupted + timedelta(seconds=policy.grace_seconds)
    if row.interruptions > policy.max_interruptions or now >= until:
        return AttemptView("used")
    return AttemptView("reconnect", until)
