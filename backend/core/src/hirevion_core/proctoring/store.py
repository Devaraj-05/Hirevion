"""What the ingestion and the watcher share: the session lock, the history the rule engine reads,
server-raised events, the shapes sent to the dashboard, and what happens after a commit
(the realtime alert, the Conductor's proctor summary and the candidate's nudge)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import NotFound
from hirevion_core.interview_session import realtime
from hirevion_core.interview_session.conductor import Conductor
from hirevion_core.models import Interview, ProctorEvent, ProctorSession
from hirevion_core.proctoring import nudges, observed
from hirevion_core.proctoring.catalogue import EVENTS, RANK
from hirevion_core.proctoring.rules import GAZE, Recent, Verdict, evaluate

log = logging.getLogger(__name__)

ENDED = ("completed", "evaluating", "evaluated", "abandoned", "cancelled", "expired")
OPEN = ("in_progress", "interrupted")
MERGE_WINDOW = timedelta(seconds=15)
"""A device's report of a disconnection and the server's own sighting of it are one event when
they start this close together."""


@dataclass(slots=True)
class Change:
    """One event created or changed in a transaction, for after the commit."""

    row: ProctorEvent
    kind: str
    """`created` or `updated`."""
    severity_before: str | None = None
    notice: nudges.Nudge | None = None

    @property
    def raised(self) -> bool:
        """New, or worse than it was: the cases that count as an alert."""
        return self.kind == "created" or (
            self.severity_before is not None
            and RANK[self.row.severity] > RANK[self.severity_before]
        )


@dataclass(slots=True)
class Pending:
    """Everything to do after the transaction commits."""

    changes: list[Change] = field(default_factory=list)
    status: bool = False
    """Publish the session's devices and connection health."""


def event_json(row: ProctorEvent) -> dict[str, Any]:
    """An event as the dashboard and the report show it."""
    return {
        "id": str(row.id),
        "seq": row.seq,
        "event": row.event,
        "source": row.source,
        "origin": row.origin,
        "severity": row.severity,
        "started_at": row.started_at.isoformat(),
        "duration_ms": row.duration_ms,
        "ongoing": row.ongoing,
        "phase": row.phase,
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "details": row.details,
        "review_status": row.review_status,
        "policy_version": row.policy_version,
    }


def status_json(proctor: ProctorSession, interview_status: str | None = None) -> dict[str, Any]:
    """The devices and the connection, as the dashboard's health panel shows them."""
    state = {name: observed.state_of(proctor.observed, name) for name in observed.CHANNELS}
    paused = bool(proctor.observed.get("paused"))
    if proctor.status == "closed":
        connection = "closed"
    elif paused or interview_status == "interrupted":
        connection = "interrupted"
    else:
        connection = "gap" if state["heartbeat"] == "down" else "ok"
    last = proctor.last_status or {}
    return {
        "session": proctor.status,
        "devices": {name: state[name] for name in ("camera", "mic", "screen", "third_eye")},
        "connection": {
            "state": connection,
            "last_heartbeat_at": proctor.last_heartbeat_at.isoformat()
            if proctor.last_heartbeat_at
            else None,
        },
        "displays": last.get("displays"),
        "cpu_percent": last.get("cpu_percent"),
        "vision_fps": last.get("vision_fps"),
        "reported": {key: last.get(key) for key in ("camera", "mic", "screen", "third_eye")},
    }


async def lock_session(
    session: AsyncSession, session_id: UUID, interview_id: UUID | None = None
) -> ProctorSession:
    """The proctor session, locked; it must belong to `interview_id` when that is given."""
    row = await session.scalar(
        select(ProctorSession).where(ProctorSession.id == session_id).with_for_update()
    )
    if row is None or (interview_id is not None and row.interview_id != interview_id):
        raise NotFound("proctor-session-not-found", "No such proctor session")
    return row


async def history(
    session: AsyncSession, proctor: ProctorSession, since: datetime
) -> list[tuple[str, str, datetime, str]]:
    """`(event, severity, started_at, id)` of this session's warnings and criticals since
    `since`: what escalation and corroboration look at."""
    rows = await session.execute(
        select(ProctorEvent.event, ProctorEvent.severity, ProctorEvent.started_at, ProctorEvent.id)
        .where(
            ProctorEvent.proctor_session_id == proctor.id,
            ProctorEvent.severity != "INFO",
            ProctorEvent.started_at >= since,
        )
        .order_by(ProctorEvent.started_at)
    )
    return [(r.event, r.severity, r.started_at, str(r.id)) for r in rows]


def recent_for(
    policy: dict[str, Any],
    rows: Sequence[tuple[str, str, datetime, str]],
    event: str,
    started_at: datetime,
    exclude: str | None = None,
) -> Recent:
    window = timedelta(seconds=int((policy.get("escalation") or {}).get("window_seconds", 600)))
    near = timedelta(seconds=int((policy.get("gaze") or {}).get("corroboration_seconds", 30)))
    repeats = sum(
        1
        for name, _, at, row_id in rows
        if name == event and row_id != exclude and started_at - window < at <= started_at
    )
    corroborating = tuple(
        row_id
        for name, _, at, row_id in rows
        if name not in (event, GAZE) and abs(at - started_at) <= near
    )
    return Recent(repeats, corroborating)


def server_note(
    verdict: Verdict, *, hint: str | None = None, category: str | None = None
) -> dict[str, Any]:
    note: dict[str, Any] = {"reasons": list(verdict.reasons)}
    if verdict.corroborated_by:
        note["corroborated_by"] = list(verdict.corroborated_by)
    if hint:
        note["severity_hint"] = hint
    if category:
        note["category"] = category
    return note


async def add_server_event(
    session: AsyncSession,
    proctor: ProctorSession,
    pending: Pending,
    *,
    event: str,
    started_at: datetime,
    duration_ms: int | None = None,
    ongoing: bool = False,
    details: dict[str, Any] | None = None,
    rows: Sequence[tuple[str, str, datetime, str]] = (),
    now: datetime,
) -> ProctorEvent:
    """Raises an event the server saw itself (no sequence number)."""
    policy = proctor.policy
    verdict = evaluate(
        policy,
        event,
        duration_ms=duration_ms,
        recent=recent_for(policy, rows, event, started_at),
    )
    row = ProctorEvent(
        organization_id=proctor.organization_id,
        proctor_session_id=proctor.id,
        interview_id=proctor.interview_id,
        origin="server",
        event=event,
        source=EVENTS[event].source,
        started_at=started_at,
        duration_ms=duration_ms,
        ongoing=ongoing,
        severity=verdict.severity,
        details={**(details or {}), "server": server_note(verdict)},
        policy_version=proctor.policy_version,
    )
    session.add(row)
    await session.flush()
    change = Change(row, "created")
    plan_nudge(proctor, change, now)
    pending.changes.append(change)
    return row


def plan_nudge(proctor: ProctorSession, change: Change, now: datetime) -> None:
    """Plans the candidate's nudge for a new or worsened event, recording it on the session."""
    if not change.raised or RANK[change.row.severity] < RANK["WARNING"]:
        return
    state = dict(proctor.nudges or {})
    notice = nudges.plan(
        proctor.policy,
        state,
        event_id=str(change.row.id),
        event=change.row.event,
        severity=change.row.severity,
        now=now,
    )
    if notice is not None:
        proctor.nudges = state
        change.notice = notice


def interview_gone(interview: Interview) -> bool:
    return interview.status in ENDED


async def finish(
    redis: Redis,
    conductor: Conductor | None,
    organization_id: UUID,
    interview_id: UUID,
    pending: Pending,
    proctor_status: dict[str, Any] | None,
) -> None:
    """After the commit: the alerts first (the dashboard's latency), then the interview's side.
    Nothing here may fail the request that caused it: the events are already stored."""
    for change in pending.changes:
        try:
            await realtime.publish(
                redis,
                interview_id,
                "PROCTOR_EVENT",
                {**event_json(change.row), "change": change.kind},
            )
        except Exception:
            log.exception("Couldn't publish proctor event %s", change.row.id)
    if pending.status and proctor_status is not None:
        try:
            await realtime.publish(redis, interview_id, "PROCTOR_STATUS", proctor_status)
        except Exception:
            log.exception("Couldn't publish the proctor status of interview %s", interview_id)
    for change in pending.changes:
        if change.notice is not None:
            try:
                await nudges.deliver(redis, interview_id, change.notice)
            except Exception:
                log.exception("Couldn't deliver a nudge for interview %s", interview_id)
        if conductor is not None and change.raised and RANK[change.row.severity] >= RANK["WARNING"]:
            kind = (change.notice.kind if change.notice else None) or change.row.event.lower()
            try:
                await conductor.note_proctor_event(
                    organization_id, interview_id, kind, change.row.severity.lower()
                )
            except Exception:
                log.exception("Couldn't note proctor event %s in the interview", change.row.id)
