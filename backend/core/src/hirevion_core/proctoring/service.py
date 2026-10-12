"""The proctoring engine (PRD §54): the desktop's calls, the server's own sightings and the
watcher that turns both into events.

    sources -> normaliser -> temporal aggregator -> rule engine -> evidence manager -> severity
            -> realtime alert (after the commit) -> report (the tables)

A batch is handled in one transaction under a lock on the proctor session, so a retried or
overlapping batch can't store anything twice. The alert is published after the commit, so the
dashboard never shows an event the database doesn't hold.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.db.session import Database
from hirevion_core.models import Interview, ProctorEvent, ProctorSession
from hirevion_core.proctoring import evidence, observed
from hirevion_core.proctoring.aggregator import SeqTracker, merge_episode, subtract_windows
from hirevion_core.proctoring.catalogue import RANK
from hirevion_core.proctoring.normaliser import (
    Incoming,
    Normalised,
    UnknownEvent,
    check_names,
    normalise,
)
from hirevion_core.proctoring.policy import build_policy, session_view
from hirevion_core.proctoring.rules import evaluate
from hirevion_core.proctoring.store import (
    ENDED,
    MERGE_WINDOW,
    OPEN,
    Change,
    Pending,
    add_server_event,
    finish,
    history,
    lock_session,
    plan_followups,
    recent_for,
    server_note,
    status_json,
)

log = logging.getLogger(__name__)

DRAIN = timedelta(minutes=10)
"""After an interview ends the desktop may still send the events it had queued."""
HISTORY = timedelta(minutes=15)
GAP_GRACE = 30
"""Numbers still missing after this many seconds are a gap in telemetry; retries and batches that
arrive out of order fill them sooner."""


def gap_event(track: str) -> str:
    """What a hole in a recorded track is (§64): a screen that stopped being captured, or any
    other track's loss as a gap in telemetry."""
    return "SCREEN_CAPTURE_STOPPED" if track.startswith("screen") else "TELEMETRY_GAP"


_UP = {"camera": "on", "mic": "on", "screen": "capturing", "third_eye": "connected"}
_DOWN = {
    "camera": {"off", "error", "blocked", "denied", "disconnected"},
    "mic": {"off", "error", "blocked", "denied", "disconnected"},
    "screen": {"stopped", "off", "error", "paused", "denied"},
    "third_eye": {"disconnected"},
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Opened:
    proctor_session_id: UUID
    policy: dict[str, Any]
    acked_through: int

    def view(self) -> dict[str, Any]:
        return {
            "proctor_session_id": str(self.proctor_session_id),
            **session_view(self.policy),
            "acked_through": self.acked_through,
        }


@dataclass(frozen=True, slots=True)
class Ack:
    acked_through: int
    missing: list[int]


@dataclass(frozen=True, slots=True)
class SnapshotRequest:
    """A screen or camera picture the server wants taken now, for an event."""

    request_id: UUID
    event_id: UUID
    kind: str
    requested_at: datetime


def _when(ref: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(ref["requested_at"]))


@dataclass(frozen=True, slots=True)
class HeartbeatAck:
    server_time: datetime
    missing: list[int]
    snapshots: list[SnapshotRequest]


def heartbeat_vote(channel: str, reported: str | None) -> observed.State:
    if reported is None:
        return "unknown"
    value = reported.lower()
    if value == _UP[channel]:
        return "up"
    return "down" if value in _DOWN[channel] else "unknown"


class ProctorEngine:
    def __init__(
        self,
        db: Database,
        redis: Redis,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._db = db
        self._redis = redis
        self._clock = clock

    # The session.

    async def open_session(
        self, organization_id: UUID, interview_id: UUID, app_version: str
    ) -> Opened:
        """Opens the interview's proctor session, or returns the one already open."""
        now = self._clock()
        async with self._db.tenant(organization_id) as session:
            interview = await session.get(Interview, interview_id)
            if interview is None:
                raise NotFound("interview-not-found", "No such interview")
            existing = await session.scalar(
                select(ProctorSession).where(ProctorSession.interview_id == interview_id)
            )
            if existing is None:
                if interview.status in ENDED:
                    raise Conflict("proctor-session-closed", "The interview is over")
                if interview.status not in OPEN:
                    raise Conflict("interview-not-open", "The interview hasn't started")
                existing = await self._create(session, interview, app_version, now)
            elif existing.status == "closed":
                raise Conflict("proctor-session-closed", "The interview is over")
            else:
                existing.app_version = app_version[:40]
            opened = Opened(existing.id, copy.deepcopy(existing.policy), existing.acked_through)
        await self._publish_status(organization_id, interview_id)
        return opened

    async def _create(
        self, session: AsyncSession, interview: Interview, app_version: str, now: datetime
    ) -> ProctorSession:
        policy = await build_policy(session, interview)
        row = ProctorSession(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            app_version=app_version[:40],
            level=policy["level"],
            policy_version=policy["policy_version"],
            policy=policy,
            opened_at=now,
            watch_at=now + timedelta(seconds=policy["heartbeat_grace_seconds"]),
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            # A second call raced the first: the other one's session is the one.
            existing = await session.scalar(
                select(ProctorSession).where(ProctorSession.interview_id == interview.id)
            )
            if existing is None:
                raise
            return existing
        return row

    async def _publish_status(self, organization_id: UUID, interview_id: UUID) -> None:
        from hirevion_core.interview_session import realtime

        try:
            async with self._db.tenant(organization_id) as session:
                proctor = await session.scalar(
                    select(ProctorSession).where(ProctorSession.interview_id == interview_id)
                )
                body = status_json(proctor) if proctor is not None else None
            if body is not None:
                await realtime.publish(self._redis, interview_id, "PROCTOR_STATUS", body)
        except Exception:
            log.exception("Couldn't publish the proctor status of interview %s", interview_id)

    @staticmethod
    def _gate(
        proctor: ProctorSession, interview: Interview, now: datetime, *, events: bool
    ) -> None:
        """Refuses calls for a session whose interview is over (events get a drain window)."""
        if proctor.status == "closed" or interview.status in ENDED:
            ended = proctor.closed_at or interview.ended_at or interview.completed_at or now
            if not events or now - ended > DRAIN:
                raise Conflict("proctor-session-closed", "The interview is over")
            return
        if interview.status not in OPEN:
            raise Conflict("interview-not-open", "The interview hasn't started")

    # Events from the desktop.

    async def ingest(
        self,
        organization_id: UUID,
        interview_id: UUID,
        session_id: UUID,
        items: list[Incoming],
    ) -> Ack:
        try:
            check_names(items)
        except UnknownEvent as error:
            raise Invalid("unknown-event", "The batch holds an event that isn't known") from error
        now = self._clock()
        pending = Pending()
        async with self._db.tenant(organization_id) as session:
            proctor = await lock_session(session, session_id, interview_id)
            interview = await session.get_one(Interview, interview_id)
            self._gate(proctor, interview, now, events=True)
            if len(items) > int(proctor.policy.get("batch_max_events", 100)):
                raise Invalid("batch-too-large", "The batch holds more events than allowed")
            tracker = SeqTracker(proctor.max_seq, proctor.gaps)
            by_seq = {item.seq: item for item in reversed(items)}
            if any(tracker.too_far(seq) for seq in by_seq):
                raise Invalid("seq-out-of-range", "A sequence number is out of range")
            policy = proctor.policy
            if policy.get("level") == "off":
                # Proctoring wasn't agreed to: acknowledge, store nothing.
                for seq in sorted(by_seq):
                    tracker.offer(seq, now.timestamp())
            else:
                # The times the rules and the history work with are the normalised ones: naive
                # times are taken as UTC, and a clock far ahead is clamped.
                events = {seq: normalise(by_seq[seq], policy, now=now) for seq in by_seq}
                window = int((policy.get("escalation") or {}).get("window_seconds", 600))
                since = min(n.started_at for n in events.values()) - timedelta(seconds=window)
                rows = await history(session, proctor, since)
                for seq in sorted(by_seq):
                    if tracker.offer(seq, now.timestamp()).status == "duplicate":
                        continue
                    change = await self._store(session, proctor, events[seq], rows, now)
                    if change is not None:
                        pending.changes.append(change)
            proctor.max_seq = tracker.max_seq
            proctor.gaps = tracker.to_json()
            proctor.acked_through = tracker.acked_through
            self._watch_gaps(proctor, tracker)
            ack = Ack(tracker.acked_through, tracker.missing())
        await finish(self._redis, organization_id, interview_id, pending, None)
        return ack

    async def _store(
        self,
        session: AsyncSession,
        proctor: ProctorSession,
        n: Normalised,
        rows: list[tuple[str, str, datetime, str]],
        now: datetime,
    ) -> Change | None:
        policy = proctor.policy
        target = await self._target(session, proctor, n)
        recent = recent_for(policy, rows, n.event, n.started_at, str(target.id) if target else None)
        unchanged = False
        if target is None:
            verdict = evaluate(
                policy, n.event, duration_ms=n.duration_ms, category=n.category, recent=recent
            )
            row = ProctorEvent(
                organization_id=proctor.organization_id,
                proctor_session_id=proctor.id,
                interview_id=proctor.interview_id,
                seq=n.seq,
                last_seq=n.seq,
                origin="client",
                event=n.event,
                source=n.source,
                started_at=n.started_at,
                duration_ms=n.duration_ms,
                ongoing=n.ongoing,
                confidence=None if n.confidence is None else Decimal(str(n.confidence)),
                severity=verdict.severity,
                phase=n.phase,
                details={
                    **n.details,
                    "server": server_note(verdict, hint=n.hint, category=n.category),
                },
                policy_version=proctor.policy_version,
            )
            session.add(row)
            await session.flush()
            change = Change(row, "created")
        else:
            row = target
            merged = merge_episode(
                {
                    "phase": row.phase,
                    "ongoing": row.ongoing,
                    "details": dict(row.details),
                    "duration_ms": row.duration_ms,
                    "confidence": float(row.confidence) if row.confidence is not None else None,
                    "last_seq": row.last_seq,
                },
                n,
            )
            if row.origin == "server" or row.details.get("server_confirmed"):
                # What the server saw itself keeps its clock; the device only adds to it.
                merged["duration_ms"] = max(row.duration_ms or 0, n.duration_ms or 0)
                merged["ongoing"] = row.ongoing
                merged["details"]["client_reported"] = True
            verdict = evaluate(
                policy,
                row.event,
                duration_ms=merged["duration_ms"],
                category=n.category,
                recent=recent,
            )
            before = row.severity
            severity = verdict.severity if RANK[verdict.severity] > RANK[before] else before
            snapshot = (row.phase, row.duration_ms, row.ongoing, row.severity, row.last_seq)
            row.phase, row.ongoing, row.duration_ms = (
                merged["phase"],
                merged["ongoing"],
                merged["duration_ms"],
            )
            row.confidence, row.last_seq, row.severity = (
                merged["confidence"],
                merged["last_seq"],
                severity,
            )
            row.details = {
                **merged["details"],
                "server": server_note(verdict, hint=n.hint, category=n.category),
            }
            await session.flush()
            change = Change(row, "updated", severity_before=before)
            unchanged = snapshot == (
                row.phase,
                row.duration_ms,
                row.ongoing,
                row.severity,
                row.last_seq,
            )
        # Evidence is attached whatever else a repeated report changed.
        refused = await evidence.link(session, proctor, row, n.evidence)
        if refused:
            row.details = {
                **row.details,
                "server": {**row.details.get("server", {}), "rejected_evidence": refused},
            }
        if target is not None and unchanged:
            return None
        await plan_followups(session, proctor, change, now)
        rows[:] = [r for r in rows if r[3] != str(row.id)]
        if row.severity != "INFO":
            rows.append((row.event, row.severity, row.started_at, str(row.id)))
        return change

    @staticmethod
    async def _target(
        session: AsyncSession, proctor: ProctorSession, n: Normalised
    ) -> ProctorEvent | None:
        """The stored event this one belongs to: the episode it continues, or the server's own
        sighting of the same disconnection."""
        if n.phase is not None:
            episode = await session.scalar(
                select(ProctorEvent).where(
                    ProctorEvent.proctor_session_id == proctor.id,
                    ProctorEvent.event == n.event,
                    ProctorEvent.started_at == n.started_at,
                    ProctorEvent.phase.is_not(None),
                    ProctorEvent.origin == "client",
                )
            )
            if episode is not None:
                return episode
        if n.event in observed.CHANNEL_OF_EVENT:
            return await session.scalar(
                select(ProctorEvent)
                .where(
                    ProctorEvent.proctor_session_id == proctor.id,
                    ProctorEvent.event == n.event,
                    ProctorEvent.origin == "server",
                    ProctorEvent.started_at >= n.started_at - MERGE_WINDOW,
                    ProctorEvent.started_at <= n.started_at + MERGE_WINDOW,
                )
                .order_by(ProctorEvent.started_at)
                .limit(1)
            )
        return None

    # Heartbeats.

    async def heartbeat(
        self, organization_id: UUID, interview_id: UUID, session_id: UUID, body: dict[str, Any]
    ) -> HeartbeatAck:
        now = self._clock()
        pending = Pending()
        async with self._db.tenant(organization_id) as session:
            proctor = await lock_session(session, session_id, interview_id)
            interview = await session.get_one(Interview, interview_id)
            self._gate(proctor, interview, now, events=False)
            tracker = SeqTracker(proctor.max_seq, proctor.gaps)
            missing = tracker.missing(high=int(body.get("seq_high") or 0))
            before = status_json(proctor, interview.status)
            proctor.last_heartbeat_at = now
            proctor.heartbeats += 1
            proctor.last_status = {**body, "at": now.isoformat()}
            if proctor.policy.get("level") != "off" and not proctor.observed.get("paused"):
                state = copy.deepcopy(proctor.observed)
                observed.vote(state, "heartbeat", "beat", "up", now)
                for channel in ("camera", "mic", "screen", "third_eye"):
                    vote = heartbeat_vote(channel, body.get(channel))
                    observed.vote(state, channel, "heartbeat", vote, now)
                proctor.observed = state
                proctor.watch_at = now + timedelta(
                    seconds=1 if self._pending(state) else self._grace(proctor)
                )
            after = status_json(proctor, interview.status)
            pending.status = _health(before) != _health(after) or proctor.heartbeats % 6 == 0
            snapshots = [
                SnapshotRequest(r.id, r.proctor_event_id, str(r.ref["capture"]), _when(r.ref))
                for r in await evidence.pending_requests(session, proctor, now)
                if r.proctor_event_id is not None
            ]
        await finish(self._redis, organization_id, interview_id, pending, after)
        return HeartbeatAck(now, missing, snapshots)

    @staticmethod
    def _grace(proctor: ProctorSession) -> int:
        return int(proctor.policy.get("heartbeat_grace_seconds", 20)) + 1

    @staticmethod
    def _pending(state: dict[str, Any]) -> bool:
        return any(
            observed.state_of(state, name) == "down" and observed.event_id(state, name) is None
            for name in observed.CHANNELS
        )

    # What the server sees itself.

    async def observe(
        self,
        organization_id: UUID,
        interview_id: UUID,
        channel: str,
        source: str,
        state: observed.State,
        at: datetime,
    ) -> None:
        """A view of a channel from `source` (LiveKit's webhooks); the watcher acts on it."""
        if channel not in observed.CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        now = self._clock()
        async with self._db.tenant(organization_id) as session:
            proctor = await session.scalar(
                select(ProctorSession)
                .where(ProctorSession.interview_id == interview_id)
                .with_for_update()
            )
            if proctor is None or proctor.status != "open" or proctor.observed.get("paused"):
                return
            if proctor.policy.get("level") == "off":
                return
            views = copy.deepcopy(proctor.observed)
            observed.vote(views, channel, source, state, at)
            proctor.observed = views
            proctor.watch_at = now

    async def wake(self, organization_id: UUID, interview_id: UUID) -> None:
        """Asks the watcher to look at the interview's session now (its state just changed)."""
        async with self._db.tenant(organization_id) as session:
            proctor = await session.scalar(
                select(ProctorSession)
                .where(ProctorSession.interview_id == interview_id, ProctorSession.status == "open")
                .with_for_update()
            )
            if proctor is not None:
                proctor.watch_at = self._clock()

    async def record_gap(
        self,
        organization_id: UUID,
        interview_id: UUID,
        track: str,
        started_at: datetime,
        duration_ms: int,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """A finished gap in a recorded `track` (`recording.gap` of kind `missing` or
        `corrupt`): `SCREEN_CAPTURE_STOPPED` for a screen, `TELEMETRY_GAP` for the rest. A gap
        the server already saw as it happened (a stall) is the same event, lengthened. True if
        it became or changed an event."""
        kind = track
        event = gap_event(track)
        now = self._clock()
        pending = Pending()
        duration = max(0, duration_ms)
        async with self._db.tenant(organization_id) as session:
            proctor = await session.scalar(
                select(ProctorSession)
                .where(ProctorSession.interview_id == interview_id)
                .with_for_update()
            )
            if proctor is None or proctor.policy.get("level") == "off":
                return False
            # A hole while the candidate was away (an interruption the resume policy excuses) is
            # no violation: only the parts outside the interruptions count.
            windows = await self._interruptions(session, proctor, now)
            end = started_at + timedelta(milliseconds=duration)
            pieces = subtract_windows(started_at, end, windows)
            for piece_start, piece_end in pieces:
                length = int((piece_end - piece_start).total_seconds() * 1000)
                note = {"recording_gap": {"track": kind, "duration_ms": length, **(details or {})}}
                existing = await self._same_hole(
                    session, proctor, event, kind, piece_start, piece_end
                )
                if existing is not None:
                    before = existing.severity
                    longest = max(existing.duration_ms or 0, length)
                    verdict = evaluate(proctor.policy, event, duration_ms=longest)
                    existing.duration_ms = longest
                    existing.details = {**existing.details, **note}
                    change = Change(existing, "updated", severity_before=before)
                    if RANK[verdict.severity] > RANK[before]:
                        existing.severity = verdict.severity
                        existing.details = {**existing.details, "server": server_note(verdict)}
                        await plan_followups(session, proctor, change, now)
                    pending.changes.append(change)
                else:
                    rows = await history(session, proctor, piece_start - HISTORY)
                    await add_server_event(
                        session,
                        proctor,
                        pending,
                        event=event,
                        started_at=piece_start,
                        duration_ms=length,
                        details={"reason": "recording_gap", **note},
                        rows=rows,
                        now=now,
                    )
            if not pieces:
                return False
        await finish(self._redis, organization_id, interview_id, pending, None)
        return True

    @staticmethod
    async def _same_hole(
        session: AsyncSession,
        proctor: ProctorSession,
        event: str,
        track: str,
        start: datetime,
        end: datetime,
    ) -> ProctorEvent | None:
        """The event that already stands for this hole: a screen's stop around the same time, or
        the telemetry gap raised for the same track by a stall the server saw as it happened."""
        candidates = await session.scalars(
            select(ProctorEvent)
            .where(
                ProctorEvent.proctor_session_id == proctor.id,
                ProctorEvent.event == event,
                ProctorEvent.started_at <= end + MERGE_WINDOW,
                ProctorEvent.started_at >= start - MERGE_WINDOW,
            )
            .order_by(ProctorEvent.started_at)
        )
        for row in candidates:
            if event != "TELEMETRY_GAP":
                return row
            # Telemetry gaps are many kinds; this one must be about the same track.
            hole = row.details.get("recording_gap") or {}
            if hole.get("track") == track or f"upload:{track}" in (
                row.details.get("sources") or []
            ):
                return row
        return None

    @staticmethod
    async def _interruptions(
        session: AsyncSession, proctor: ProctorSession, now: datetime
    ) -> list[tuple[datetime, datetime]]:
        """When the candidate was away: from each SESSION_INTERRUPTED to the next
        SESSION_RESUMED, or to now while the session is still paused."""
        marks = await session.execute(
            select(ProctorEvent.event, ProctorEvent.started_at)
            .where(
                ProctorEvent.proctor_session_id == proctor.id,
                ProctorEvent.event.in_(("SESSION_INTERRUPTED", "SESSION_RESUMED")),
            )
            .order_by(ProctorEvent.started_at)
        )
        windows: list[tuple[datetime, datetime]] = []
        opened: datetime | None = None
        for name, at in marks:
            if name == "SESSION_INTERRUPTED" and opened is None:
                opened = at
            elif name == "SESSION_RESUMED" and opened is not None:
                windows.append((opened, at))
                opened = None
        if opened is not None:
            windows.append((opened, now))
        return windows

    async def observe_stall(
        self,
        organization_id: UUID,
        interview_id: UUID,
        track: str,
        stalled: bool,
        at: datetime,
    ) -> None:
        """A track the upload pipeline reports silent (`stalled`, state open) or flowing again
        (state closed): a vote from `upload:{track}`, so the watcher grows the event as the
        stall lasts. Screens vote on the screen channel, other tracks on the heartbeat's."""
        channel = "screen" if track.startswith("screen") else "heartbeat"
        await self.observe(
            organization_id,
            interview_id,
            channel,
            f"upload:{track}",
            "down" if stalled else "up",
            at,
        )

    # The watcher.

    async def tick(
        self, organization_id: UUID, session_id: UUID, *, now: datetime | None = None
    ) -> None:
        """Looks at one proctor session: pauses or ends it with its interview, turns channels the
        server has seen down into events, grows the ones still open, and closes those that came
        back."""
        now = now or self._clock()
        pending = Pending()
        body: dict[str, Any] | None = None
        async with self._db.tenant(organization_id) as session:
            proctor = await lock_session(session, session_id)
            if proctor.status != "open":
                return
            interview = await session.get_one(Interview, proctor.interview_id)
            state = copy.deepcopy(proctor.observed)
            rows = await history(session, proctor, now - HISTORY)
            if interview.status in ENDED:
                await self._end(session, proctor, state, pending, rows, now)
            elif interview.status == "interrupted":
                if not state.get("paused"):
                    await self._pause(session, proctor, state, pending, rows, now)
                proctor.watch_at = now + timedelta(seconds=10)
            elif proctor.policy.get("level") == "off":
                proctor.watch_at = None
            else:
                if state.get("paused"):
                    await self._resume(session, proctor, state, pending, rows, now)
                await self._evaluate(session, proctor, state, pending, rows, now)
                proctor.watch_at = self._next_look(proctor, state, now)
            proctor.observed = state
            pending.status = pending.status or bool(pending.changes)
            body = status_json(proctor, interview.status)
        await finish(self._redis, organization_id, proctor.interview_id, pending, body)

    @staticmethod
    def _watch_gaps(proctor: ProctorSession, tracker: SeqTracker) -> None:
        """Makes sure the watcher looks when the earliest missing range becomes overdue."""
        due = tracker.next_report(GAP_GRACE)
        if due is not None:
            at = datetime.fromtimestamp(due, UTC)
            if proctor.watch_at is None or at < proctor.watch_at:
                proctor.watch_at = at

    def _next_look(self, proctor: ProctorSession, state: dict[str, Any], now: datetime) -> datetime:
        soon = now + timedelta(seconds=1)
        deadline = (proctor.last_heartbeat_at or proctor.opened_at) + timedelta(
            seconds=self._grace(proctor)
        )
        if self._pending(state):
            look = soon
        elif any(observed.event_id(state, name) for name in observed.CHANNELS):
            look = min(now + timedelta(seconds=5), max(deadline, soon))
        else:
            look = max(deadline, soon)
        due = SeqTracker(proctor.max_seq, proctor.gaps).next_report(GAP_GRACE)
        if due is not None:
            look = min(look, max(datetime.fromtimestamp(due, UTC), soon))
        return look

    async def _evaluate(
        self,
        session: AsyncSession,
        proctor: ProctorSession,
        state: dict[str, Any],
        pending: Pending,
        rows: list[tuple[str, str, datetime, str]],
        now: datetime,
    ) -> None:
        policy = proctor.policy
        tracker = SeqTracker(proctor.max_seq, proctor.gaps)
        overdue = tracker.overdue(now.timestamp(), GAP_GRACE)
        for low, high in overdue:
            # Numbers that are still missing after the grace period: reported once.
            await add_server_event(
                session,
                proctor,
                pending,
                event="TELEMETRY_GAP",
                started_at=now,
                duration_ms=0,
                details={"reason": "sequence_gap", "from_seq": low, "to_seq": high},
                rows=rows,
                now=now,
            )
        if overdue:
            tracker.mark_reported(overdue)
            proctor.gaps = tracker.to_json()
        last = proctor.last_heartbeat_at or proctor.opened_at
        if (now - last).total_seconds() > int(policy.get("heartbeat_grace_seconds", 20)):
            observed.vote(state, "heartbeat", "beat", "down", last)
        debounce = float(policy.get("observe_seconds", 5))
        for name, channel in observed.CHANNELS.items():
            move = observed.step(state, name, now, debounce)
            if move.action == "open" and move.started_at is not None:
                row = await self._adopt(session, proctor, channel.down_event, move.started_at)
                if row is None:
                    row = await add_server_event(
                        session,
                        proctor,
                        pending,
                        event=channel.down_event,
                        started_at=move.started_at,
                        duration_ms=int((now - move.started_at).total_seconds() * 1000),
                        ongoing=True,
                        details={"observed_channel": name, "sources": self._sources(state, name)},
                        rows=rows,
                        now=now,
                    )
                observed.set_event(state, name, str(row.id))
            elif move.action in ("update", "close"):
                await self._advance(session, proctor, state, pending, name, move, now)
            elif move.action == "clear":
                observed.set_event(state, name, None)

    @staticmethod
    def _sources(state: dict[str, Any], name: str) -> list[str]:
        votes = (state.get(name) or {}).get("votes") or {}
        return sorted(source for source, vote in votes.items() if vote["state"] == "down")

    @staticmethod
    async def _adopt(
        session: AsyncSession, proctor: ProctorSession, event: str, since: datetime
    ) -> ProctorEvent | None:
        """The device's own report of the same disconnection, if it already sent one."""
        row = await session.scalar(
            select(ProctorEvent)
            .where(
                ProctorEvent.proctor_session_id == proctor.id,
                ProctorEvent.event == event,
                ProctorEvent.origin == "client",
                ProctorEvent.started_at >= since - MERGE_WINDOW,
                ProctorEvent.started_at <= since + MERGE_WINDOW,
            )
            .order_by(ProctorEvent.started_at)
            .limit(1)
        )
        if row is not None:
            row.details = {**row.details, "server_confirmed": True}
        return row

    async def _advance(
        self,
        session: AsyncSession,
        proctor: ProctorSession,
        state: dict[str, Any],
        pending: Pending,
        name: str,
        move: observed.Step,
        now: datetime,
    ) -> None:
        """Grows an open event with the time the channel stays down, or closes it."""
        channel = observed.CHANNELS[name]
        event_id = observed.event_id(state, name)
        row = await session.get(ProctorEvent, UUID(event_id)) if event_id else None
        if row is None:
            observed.set_event(state, name, None)
            return
        end = move.ended_at or now
        since = move.started_at or row.started_at
        closing = move.action == "close"
        duration = max(row.duration_ms or 0, int((end - since).total_seconds() * 1000))
        verdict = evaluate(proctor.policy, row.event, duration_ms=duration)
        before = row.severity
        worse = RANK[verdict.severity] > RANK[before]
        if closing or worse or duration - (row.duration_ms or 0) >= 5000:
            row.duration_ms = duration
            row.ongoing = not closing
            if worse:
                row.severity = verdict.severity
                row.details = {**row.details, "server": server_note(verdict)}
            change = Change(row, "updated", severity_before=before)
            if worse:
                await plan_followups(session, proctor, change, now)
            if closing or worse:
                pending.changes.append(change)
        if closing:
            observed.set_event(state, name, None)
            if channel.up_event is not None:
                await add_server_event(
                    session,
                    proctor,
                    pending,
                    event=channel.up_event,
                    started_at=end,
                    details={"observed_channel": name, "after_ms": duration},
                    now=now,
                )

    async def _pause(
        self,
        session: AsyncSession,
        proctor: ProctorSession,
        state: dict[str, Any],
        pending: Pending,
        rows: list[tuple[str, str, datetime, str]],
        now: datetime,
    ) -> None:
        """The candidate dropped out of the interview: end what was open, and expect nothing."""
        await self._close_open(session, proctor, state, pending, now)
        observed.reset(state)
        state["paused"] = True
        await add_server_event(
            session,
            proctor,
            pending,
            event="SESSION_INTERRUPTED",
            started_at=now,
            rows=rows,
            now=now,
        )
        pending.status = True

    async def _resume(
        self,
        session: AsyncSession,
        proctor: ProctorSession,
        state: dict[str, Any],
        pending: Pending,
        rows: list[tuple[str, str, datetime, str]],
        now: datetime,
    ) -> None:
        observed.reset(state)
        state["paused"] = False
        proctor.last_heartbeat_at = now
        await add_server_event(
            session, proctor, pending, event="SESSION_RESUMED", started_at=now, rows=rows, now=now
        )
        pending.status = True

    async def _close_open(
        self,
        session: AsyncSession,
        proctor: ProctorSession,
        state: dict[str, Any],
        pending: Pending,
        now: datetime,
    ) -> None:
        for name in observed.CHANNELS:
            event_id = observed.event_id(state, name)
            if not event_id:
                continue
            row = await session.get(ProctorEvent, UUID(event_id))
            if row is not None and row.ongoing:
                before = row.severity
                since = observed.down_since(state, name) or row.started_at
                row.duration_ms = max(
                    row.duration_ms or 0, int((now - since).total_seconds() * 1000)
                )
                row.ongoing = False
                verdict = evaluate(proctor.policy, row.event, duration_ms=row.duration_ms)
                if RANK[verdict.severity] > RANK[before]:
                    row.severity = verdict.severity
                pending.changes.append(Change(row, "updated", severity_before=before))
            observed.set_event(state, name, None)

    async def _end(
        self,
        session: AsyncSession,
        proctor: ProctorSession,
        state: dict[str, Any],
        pending: Pending,
        rows: list[tuple[str, str, datetime, str]],
        now: datetime,
    ) -> None:
        await self._close_open(session, proctor, state, pending, now)
        proctor.status = "closed"
        proctor.closed_at = now
        proctor.watch_at = None
        pending.status = True

    # Evidence.

    async def evidence_upload(
        self,
        organization_id: UUID,
        interview_id: UUID,
        session_id: UUID,
        storage: evidence.Uploads,
        *,
        kind: str,
        seq: int | None,
        request_id: UUID | None = None,
        content_type: str,
        size: int,
        sha256: str,
    ) -> evidence.UploadSlot:
        now = self._clock()
        async with self._db.tenant(organization_id) as session:
            proctor = await lock_session(session, session_id, interview_id)
            interview = await session.get_one(Interview, interview_id)
            self._gate(proctor, interview, now, events=True)
            return await evidence.issue_upload(
                session,
                proctor,
                storage,
                kind=kind,
                seq=seq,
                request_id=request_id,
                content_type=content_type,
                size=size,
                sha256=sha256,
            )

    async def sessions_due(
        self, now: datetime | None = None, limit: int = 200
    ) -> list[tuple[UUID, UUID]]:
        from sqlalchemy import text

        async with self._db.unscoped() as session:
            result = await session.execute(
                text("SELECT * FROM scheduler_proctor_sessions_due(:now, :limit)"),
                {"now": now or self._clock(), "limit": limit},
            )
            return [(row.organization_id, row.proctor_session_id) for row in result]


def _health(body: dict[str, Any]) -> tuple[Any, ...]:
    """What the dashboard's health panel shows, without the figures that change every beat."""
    return (body["devices"], body["connection"]["state"], body["displays"], body["reported"])
