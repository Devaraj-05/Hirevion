"""The Conductor runs the interview's turns around the engine (SP-09; master plan §6.8
continuity). Whichever process takes a turn (the API in text mode, the agent in voice mode, a
restarted agent after a crash), it goes the same way:

1. take the interview's turn lock in Valkey, so turns never interleave;
2. load the checkpoint (`interview_sessions.state`) in a short transaction;
3. analyse the answer and phrase any follow-up with no transaction open (the models are slow);
4. step the orchestrator;
5. save the new checkpoint with an optimistic `state_seq` check, and in the same transaction
   the question asked, the answer, the questions closed, both transcript segments, the
   interview's events and, when it ended, its completion;
6. after the commit, publish §91's events and refresh the hot copy in Valkey.

So every committed turn survives a crash, and an uncommitted one is simply asked again.

Interruptions follow the interview's resume policy: the candidate leaving the room pauses the
interview (`interrupted`, the clock paused); `start` again within the grace period and under
the interruption limit resumes it with a recap; the scheduler abandons it after the grace.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Conflict, Gone, Invalid, NotFound, TooLarge
from hirevion_core.ai.types import LLMService
from hirevion_core.db.session import Database
from hirevion_core.engine.analysis import Analysed, AnswerAnalyzer
from hirevion_core.engine.context import ContextBuilder
from hirevion_core.engine.followups import FollowUpGenerator
from hirevion_core.engine.orchestrator import Control, EngineError, Orchestrator, Turn, build_state
from hirevion_core.engine.state import AskedQuestion, InterviewState
from hirevion_core.interview_session import realtime
from hirevion_core.interview_session.briefing import (
    NOTICE_VERSION,
    answer_mode,
    duration_minutes,
    resume_policy,
    third_eye_mode,
)
from hirevion_core.interview_session.media import MediaControl, MediaError, ParticipantToken
from hirevion_core.interview_session.transcripts import segment
from hirevion_core.interviews.lifecycle import By, record_event, transition
from hirevion_core.models import (
    Application,
    CandidateAccount,
    Consent,
    Interview,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    SystemCheckResult,
    Transcript,
    WorkspaceSnapshot,
)
from hirevion_core.screening.engine import record_stage

log = logging.getLogger(__name__)

LOCK_TTL_MS = 30_000
LOCK_WAIT_SECONDS = 10.0
AGENT_TTL_SECONDS = 8
HOT_TTL_SECONDS = 6 * 3600
WORKSPACE_MAX_BYTES = 256 * 1024
ANSWER_MAX = 20_000
TOKEN_SLACK = timedelta(minutes=15)
VOICE_STATES = ("listening", "thinking", "speaking", "waiting", "paused", "ended", "error")
STARTABLE = ("invited", "in_progress", "interrupted")
_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
    "else return 0 end"
)


def _now() -> datetime:
    return datetime.now(UTC)


def lock_key(interview_id: UUID) -> str:
    return f"hv:lock:iv:{interview_id}"


def agent_key(interview_id: UUID) -> str:
    return f"hv:iv:{interview_id}:agent"


def hot_key(interview_id: UUID) -> str:
    return f"hv:iv:{interview_id}:hot"


@dataclass(frozen=True, slots=True)
class QuestionView:
    id: str
    index: int
    text: str
    type: str
    time_limit_seconds: int | None
    workspace: str
    languages: list[str]


@dataclass(frozen=True, slots=True)
class SessionView:
    """The contract's `state`."""

    status: str
    started_at: datetime | None
    deadline_at: datetime | None
    remaining_seconds: int
    third_eye: str
    workspace: str
    answer_mode: str
    question: QuestionView | None
    voice: str
    stage: str
    message: str | None
    notice: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class StartResult:
    view: SessionView
    media: ParticipantToken | None
    resumed: bool


@dataclass(frozen=True, slots=True)
class TurnResult:
    view: SessionView
    say: str
    asked: QuestionView | None
    completed: str | None


@dataclass(frozen=True, slots=True)
class Speech:
    """When the candidate spoke, and how sure the recogniser was (voice mode)."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    confidence: float | None = None


def question_view(question: AskedQuestion | None) -> QuestionView | None:
    if question is None:
        return None
    return QuestionView(
        id=question.id,
        index=question.position,
        text=question.text,
        type=question.type or question.kind,
        time_limit_seconds=question.time_limit_seconds,
        workspace=question.workspace,
        languages=list(question.languages),
    )


def session_view(
    interview: Interview,
    row: InterviewSession | None,
    state: InterviewState | None,
    now: datetime,
    *,
    voice: str | None = None,
    message: str | None = None,
    notice: dict[str, Any] | None = None,
) -> SessionView:
    policy = interview.policy or {}
    question = state.current if state is not None else None
    ended = interview.status in ("completed", "evaluating", "evaluated", "abandoned")
    if state is not None and state.ended:
        ended = True
    if voice not in VOICE_STATES:
        voice = None
    paused = interview.status == "interrupted"
    return SessionView(
        status=interview.status,
        started_at=row.started_at if row is not None else None,
        deadline_at=state.clock.deadline_at if state is not None else None,
        remaining_seconds=state.clock.remaining(now) if state is not None else 0,
        third_eye=third_eye_mode(policy),
        workspace=question.workspace if question is not None else "none",
        answer_mode=state.answer_mode if state is not None else answer_mode(policy),
        question=question_view(question),
        voice="ended" if ended else "paused" if paused else voice or "waiting",
        stage=state.stage if state is not None else "start",
        message=message,
        notice=notice,
    )


class Conductor:
    def __init__(
        self,
        db: Database,
        redis: Redis,
        *,
        llm: LLMService | None,
        media: MediaControl | None = None,
        origin: str = "api",
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._db = db
        self._redis = redis
        self._media = media
        self._origin = origin
        self._clock = clock
        self._analyzer = AnswerAnalyzer(llm)
        self._follow_ups = FollowUpGenerator(llm)
        self._engine = Orchestrator()

    # Locks and the hot copy.

    @asynccontextmanager
    async def _turn(self, interview_id: UUID) -> AsyncIterator[None]:
        key, token = lock_key(interview_id), uuid.uuid4().hex
        deadline = asyncio.get_running_loop().time() + LOCK_WAIT_SECONDS
        while not await self._redis.set(key, token, nx=True, px=LOCK_TTL_MS):
            if asyncio.get_running_loop().time() > deadline:
                raise Conflict("turn-in-progress", "Another turn is still being handled")
            await asyncio.sleep(0.05)
        try:
            yield
        finally:
            await self._redis.eval(_RELEASE, 1, key, token)

    async def agent_alive(self, interview_id: UUID) -> bool:
        return bool(await self._redis.exists(agent_key(interview_id)))

    async def set_voice(self, interview_id: UUID, voice: str) -> None:
        if voice in VOICE_STATES:
            await self._redis.hset(hot_key(interview_id), mapping={"voice": voice})
            await self._redis.expire(hot_key(interview_id), HOT_TTL_SECONDS)

    async def _hot(self, interview_id: UUID) -> dict[str, Any]:
        raw: dict[Any, Any] = await self._redis.hgetall(hot_key(interview_id))
        return {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }

    async def _remember(self, interview_id: UUID, turn: Turn | None, seq: int) -> None:
        mapping: dict[Any, Any] = {"seq": str(seq)}
        if turn is not None and turn.text:
            mapping["message"] = turn.text
        if turn is not None:
            mapping["notice"] = json.dumps(turn.notice) if turn.notice else ""
        await self._redis.hset(hot_key(interview_id), mapping=mapping)
        await self._redis.expire(hot_key(interview_id), HOT_TTL_SECONDS)

    # Loading and saving.

    async def _load(
        self, session: AsyncSession, interview_id: UUID, *, lock: bool = False
    ) -> tuple[Interview, InterviewSession | None]:
        statement = select(Interview).where(Interview.id == interview_id)
        if lock:
            statement = statement.with_for_update()
        interview = await session.scalar(statement)
        if interview is None:
            raise NotFound("interview-not-found", "No such interview")
        row = await session.get(InterviewSession, interview_id, with_for_update=lock)
        return interview, row

    async def _locked(
        self, session: AsyncSession, interview_id: UUID
    ) -> tuple[Interview, InterviewSession]:
        """The interview and its session row, locked, still in progress."""
        interview, row = await self._load(session, interview_id, lock=True)
        if row is None or interview.status != "in_progress":
            raise Conflict("interview-not-in-progress", f"The interview is {interview.status}")
        return interview, row

    async def _checkpoint(
        self, organization_id: UUID, interview_id: UUID
    ) -> tuple[Interview, InterviewSession, InterviewState]:
        async with self._db.tenant(organization_id) as session:
            interview, row = await self._load(session, interview_id)
            if row is None:
                raise Conflict("interview-not-started", "The interview hasn't started")
            if interview.status != "in_progress":
                raise Conflict("interview-not-in-progress", f"The interview is {interview.status}")
            return interview, row, InterviewState.from_json(row.state)

    async def _apply(
        self,
        session: AsyncSession,
        interview: Interview,
        row: InterviewSession,
        state: InterviewState,
        turn: Turn,
        now: datetime,
        *,
        by: By,
        expected_seq: int | None,
        candidate: tuple[str, str | None, Speech, Literal["voice", "text"]] | None = None,
    ) -> int:
        """Writes one turn: the checkpoint and its rows. Returns the new `state_seq`."""
        if candidate is not None and candidate[0].strip():
            text, question_id, speech, _mode = candidate
            session.add(
                segment(
                    state,
                    "candidate",
                    text,
                    start=speech.started_at or now,
                    end=speech.ended_at or now,
                    question_id=question_id,
                    confidence=speech.confidence,
                )
            )
        if turn.answer is not None and candidate is not None:
            answer = turn.answer
            session.add(
                InterviewAnswer(
                    organization_id=interview.organization_id,
                    interview_id=interview.id,
                    question_id=UUID(answer.question_id),
                    mode=candidate[3],
                    text=answer.text[:ANSWER_MAX],
                    started_at=candidate[2].started_at,
                    ended_at=candidate[2].ended_at or now,
                    late=answer.late,
                    analysis=answer.analysis,
                    quality=answer.quality,
                    flags=answer.flags,
                )
            )
        for question_id, status in turn.closed:
            await session.execute(
                update(InterviewQuestion)
                .where(InterviewQuestion.id == UUID(question_id))
                .values(status=status, closed_at=now)
            )
        if turn.asked is not None:
            asked = turn.asked
            session.add(
                InterviewQuestion(
                    id=UUID(asked.id),
                    organization_id=interview.organization_id,
                    interview_id=interview.id,
                    position=asked.position,
                    parent_id=UUID(asked.parent_id) if asked.parent_id else None,
                    kind=asked.kind,
                    stage=asked.stage,
                    skill=asked.skill,
                    topic=asked.topic,
                    difficulty=asked.difficulty,
                    type=asked.type,
                    text=asked.text,
                    source=asked.source,
                    source_ref=asked.source_ref,
                    expected_concepts=asked.expected_concepts,
                    time_limit_seconds=asked.time_limit_seconds,
                    workspace=asked.workspace,
                    languages=asked.languages,
                    status="asked",
                    asked_at=asked.asked_at,
                )
            )
        if turn.text:
            spoken_for = (
                turn.asked.id if turn.asked else (state.current.id if state.current else None)
            )
            session.add(segment(state, "ai", turn.text, start=now, question_id=spoken_for))
        await session.flush()
        for action, details in turn.events:
            await record_event(
                session,
                interview,
                action,
                By("agent", self._origin),
                from_status=interview.status,
                details=details,
            )
        if turn.completed is not None and interview.status in ("in_progress", "interrupted"):
            await self._complete(session, interview, row, state, now, by, turn.completed)
        new_seq = (expected_seq or 0) + 1 if expected_seq is not None else row.state_seq
        if expected_seq is not None:
            result = await session.execute(
                update(InterviewSession)
                .where(
                    InterviewSession.interview_id == interview.id,
                    InterviewSession.state_seq == expected_seq,
                )
                .values(
                    state=state.to_json(),
                    state_seq=new_seq,
                    deadline_at=state.clock.deadline_at,
                    paused_seconds=state.clock.paused_seconds,
                    ended_at=row.ended_at,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                raise Conflict("state-conflict", "The interview moved on; try again")
        return new_seq

    async def _complete(
        self,
        session: AsyncSession,
        interview: Interview,
        row: InterviewSession,
        state: InterviewState,
        now: datetime,
        by: By,
        reason: str,
    ) -> None:
        await transition(session, interview, "completed", "completed", by, reason=reason, now=now)
        row.ended_at = now
        application = await session.get_one(Application, interview.application_id)
        if application.stage == "interview":
            await record_stage(session, application, "interviewed", "interview_completed")
        if await session.get(Transcript, interview.id) is None:
            session.add(
                Transcript(organization_id=interview.organization_id, interview_id=interview.id)
            )
        await session.flush()

    async def _publish(
        self,
        interview_id: UUID,
        state: InterviewState,
        turn: Turn,
        now: datetime,
        *,
        answered: tuple[str, str | None, Speech, str] | None = None,
    ) -> None:
        try:
            if answered is not None and turn.answer is not None:
                await realtime.publish(
                    self._redis,
                    interview_id,
                    "ANSWER_RECEIVED",
                    {
                        "question_id": turn.answer.question_id,
                        "mode": answered[3],
                        "text": answered[0][:2000],
                        "late": turn.answer.late,
                    },
                    at=now,
                )
            if turn.text:
                await realtime.publish(
                    self._redis,
                    interview_id,
                    "AI_SPEAKING",
                    {
                        "text": turn.text,
                        "question_id": turn.asked.id if turn.asked else None,
                        "origin": self._origin,
                    },
                    at=now,
                )
            view = question_view(turn.asked)
            if turn.asked is not None and view is not None:
                await realtime.publish(
                    self._redis,
                    interview_id,
                    "QUESTION_STARTED",
                    {
                        "question_id": view.id,
                        "index": view.index,
                        "kind": turn.asked.kind,
                        "stage": turn.asked.stage,
                        "skill": turn.asked.skill,
                        "text": view.text,
                        "time_limit_seconds": view.time_limit_seconds,
                        "workspace": view.workspace,
                    },
                    at=now,
                )
            if turn.completed is not None:
                await realtime.publish(
                    self._redis,
                    interview_id,
                    "INTERVIEW_COMPLETED",
                    {"reason": turn.completed, "stage": state.stage},
                    at=now,
                )
        except Exception:
            # The turn is committed; a missed live event is only a dashboard's loss.
            log.exception("Couldn't publish the live events of interview %s", interview_id)

    async def _result(
        self,
        interview: Interview,
        row: InterviewSession,
        state: InterviewState,
        turn: Turn,
        now: datetime,
        seq: int,
    ) -> TurnResult:
        await self._remember(interview.id, turn, seq)
        hot = await self._hot(interview.id)
        view = session_view(
            interview,
            row,
            state,
            now,
            voice=hot.get("voice"),
            message=turn.text or None,
            notice=turn.notice,
        )
        return TurnResult(view, turn.text, question_view(turn.asked), turn.completed)

    # The contract.

    async def start(
        self,
        organization_id: UUID,
        interview_id: UUID,
        *,
        account_id: UUID,
        system_check_id: UUID,
        consent_id: UUID,
        token_expires_at: datetime,
        by: By,
    ) -> StartResult:
        now = self._clock()
        if self._media is not None:
            # The room first: with the media server down nothing is committed, so the interview
            # hasn't started and its clock hasn't run.
            try:
                await self._media.ensure_room(interview_id, organization_id)
            except MediaError as error:
                raise MediaUnavailable() from error
        async with self._turn(interview_id):
            async with self._db.tenant(organization_id) as session:
                interview, row = await self._load(session, interview_id, lock=True)
                self._check_startable(interview, row, now)
                check = await session.get(SystemCheckResult, system_check_id)
                if check is None or check.interview_id != interview.id or not check.passed:
                    raise Conflict("checks-incomplete", "Complete the system check first")
                consent = await session.get(Consent, consent_id)
                if (
                    consent is None
                    or consent.interview_id != interview.id
                    or not consent.complete
                    or consent.notice_version != NOTICE_VERSION
                ):
                    raise Conflict("consents-missing", "Agree to the required items first")
                if third_eye_mode(interview.policy) == "required" and not await third_eye_paired(
                    session, interview
                ):
                    raise Conflict("third-eye-required", "Pair your phone as the third camera")
                account = await session.get_one(CandidateAccount, account_id)
                turn: Turn | None = None
                resumed = interview.status != "invited"
                if interview.status == "invited":
                    row, state, turn = await self._first_start(
                        session, interview, by, now, system_check_id, consent_id
                    )
                    seq = row.state_seq
                else:
                    if row is None:
                        raise Conflict("interview-not-open", "The interview can't be resumed")
                    state = InterviewState.from_json(row.state)
                    if interview.status == "interrupted":
                        turn = await self._resume(session, interview, row, state, now, by)
                    else:
                        row.reconnects += 1
                    row.connected_at = now
                    seq = await self._apply(
                        session,
                        interview,
                        row,
                        state,
                        turn or Turn(),
                        now,
                        by=by,
                        expected_seq=row.state_seq,
                    )
                name = account.name
            await self._remember(interview.id, turn, seq)
        token = await self._connect(interview, state, name, token_expires_at)
        if turn is not None:
            await self._publish(interview.id, state, turn, now)
        hot = await self._hot(interview.id)
        view = session_view(
            interview,
            row,
            state,
            now,
            voice=hot.get("voice"),
            message=turn.text if turn and turn.text else hot.get("message") or None,
        )
        return StartResult(view, token, resumed)

    def _check_startable(
        self, interview: Interview, row: InterviewSession | None, now: datetime
    ) -> None:
        if interview.status not in STARTABLE:
            if interview.status == "expired":
                raise Gone("interview-expired", "The interview's window has closed")
            raise Conflict("interview-not-open", f"The interview is {interview.status}")
        if interview.status == "invited":
            if now < interview.starts_at:
                raise Conflict("interview-not-open", "The interview's window hasn't opened yet")
            if now >= interview.expires_at:
                raise Gone("interview-expired", "The interview's window has closed")
            return
        if row is None:
            raise Conflict("interview-not-open", "The interview can't be resumed")
        if interview.status == "interrupted":
            policy = resume_policy(interview.policy)
            grace = timedelta(seconds=policy.grace_seconds)
            interrupted = interview.interrupted_at or now
            if row.interruptions > policy.max_interruptions or now - interrupted > grace:
                raise Conflict("resume-limit-reached", "The interview can no longer be resumed")

    async def _first_start(
        self,
        session: AsyncSession,
        interview: Interview,
        by: By,
        now: datetime,
        system_check_id: UUID,
        consent_id: UUID,
    ) -> tuple[InterviewSession, InterviewState, Turn | None]:
        context = await ContextBuilder().build(session, interview)
        mode = answer_mode(interview.policy or {})
        deadline = now + timedelta(minutes=duration_minutes(interview))
        state = build_state(context, now=now, deadline=deadline, answer_mode=mode)
        await transition(session, interview, "in_progress", "started", by, now=now)
        row = InterviewSession(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            mode=mode,
            room=f"iv-{interview.id}",
            state={},
            state_seq=0,
            started_at=now,
            deadline_at=deadline,
            system_check_id=system_check_id,
            consent_id=consent_id,
            connected_at=now,
        )
        session.add(row)
        await session.flush()
        turn: Turn | None = None
        if mode == "text":
            # No agent in text mode: the API greets and asks the first question itself.
            turn = self._engine.begin(state, now)
        seq = await self._apply(
            session, interview, row, state, turn or Turn(), now, by=by, expected_seq=0
        )
        row.state_seq = seq
        return row, state, turn

    async def _resume(
        self,
        session: AsyncSession,
        interview: Interview,
        row: InterviewSession,
        state: InterviewState,
        now: datetime,
        by: By,
    ) -> Turn | None:
        paused = state.clock.resume(now, extend=resume_policy(interview.policy).pause_timer)
        await transition(
            session,
            interview,
            "in_progress",
            "resumed",
            by,
            details={"paused_seconds": paused, "interruptions": row.interruptions},
            now=now,
        )
        interview.interrupted_at = None
        if state.answer_mode == "text" and state.stage != "start":
            return self._engine.resume(state, now)
        return None

    async def _connect(
        self, interview: Interview, state: InterviewState, name: str, token_expires_at: datetime
    ) -> ParticipantToken | None:
        """The candidate's token and (in voice mode, with none alive) the agent; `start` made
        the room before committing."""
        if self._media is None:
            return None
        expires = min(token_expires_at, state.clock.deadline_at + TOKEN_SLACK)
        try:
            token = self._media.participant_token(
                interview.id, interview.candidate_id, name, expires
            )
            if state.answer_mode == "voice" and not await self.agent_alive(interview.id):
                dispatch = await self._media.dispatch_agent(interview.id, interview.organization_id)
                async with self._db.tenant(interview.organization_id) as session:
                    await session.execute(
                        update(InterviewSession)
                        .where(InterviewSession.interview_id == interview.id)
                        .values(agent_dispatch_id=dispatch)
                    )
        except MediaError as error:
            raise MediaUnavailable() from error
        return token

    async def load_state(self, organization_id: UUID, interview_id: UUID) -> InterviewState | None:
        """The checkpoint as it stands (the agent primes speech recognition from it)."""
        async with self._db.tenant(organization_id) as session:
            row = await session.get(InterviewSession, interview_id)
            return InterviewState.from_json(row.state) if row is not None and row.state else None

    async def session_state(self, organization_id: UUID, interview_id: UUID) -> SessionView:
        now = self._clock()
        async with self._db.tenant(organization_id) as session:
            interview, row = await self._load(session, interview_id)
            state = InterviewState.from_json(row.state) if row is not None and row.state else None
        hot = await self._hot(interview_id)
        notice = json.loads(hot["notice"]) if hot.get("notice") else None
        return session_view(
            interview,
            row,
            state,
            now,
            voice=hot.get("voice"),
            message=hot.get("message") or None,
            notice=notice,
        )

    async def begin(self, organization_id: UUID, interview_id: UUID, *, by: By) -> TurnResult:
        """The greeting and first question, in voice mode, once the agent is in the room; a
        restarted agent that finds the interview under way gets the recovery recap instead."""
        now = self._clock()
        async with self._turn(interview_id):
            interview, row, state = await self._checkpoint(organization_id, interview_id)
            expected = row.state_seq
            if state.stage == "start":
                turn = self._engine.begin(state, now)
            else:
                turn = self._engine.resume(state, now, recovered=True)
            async with self._db.tenant(organization_id) as session:
                interview, row = await self._locked(session, interview_id)
                seq = await self._apply(
                    session, interview, row, state, turn, now, by=by, expected_seq=expected
                )
            result = await self._result(interview, row, state, turn, now, seq)
        await self._publish(interview_id, state, turn, now)
        return result

    async def recap(self, organization_id: UUID, interview_id: UUID, *, by: By) -> TurnResult:
        """What the agent says when the candidate comes back after an interruption."""
        now = self._clock()
        async with self._turn(interview_id):
            interview, row, state = await self._checkpoint(organization_id, interview_id)
            expected = row.state_seq
            turn = self._engine.resume(state, now)
            async with self._db.tenant(organization_id) as session:
                interview, row = await self._locked(session, interview_id)
                seq = await self._apply(
                    session, interview, row, state, turn, now, by=by, expected_seq=expected
                )
            result = await self._result(interview, row, state, turn, now, seq)
        await self._publish(interview_id, state, turn, now)
        return result

    async def answer(
        self,
        organization_id: UUID,
        interview_id: UUID,
        question_id: UUID | None,
        text: str,
        *,
        mode: Literal["voice", "text"],
        by: By,
        speech: Speech | None = None,
        acknowledged: bool = False,
    ) -> TurnResult:
        """One answer to the open question (`question_id`, when given, must be it).
        `acknowledged`: the agent already played an acknowledgement."""
        if len(text) > ANSWER_MAX:
            raise Invalid("answer-too-long", "The answer is too long", field="text")
        speech = speech or Speech()
        async with self._turn(interview_id):
            for attempt in (1, 2):
                interview, row, state = await self._checkpoint(organization_id, interview_id)
                question = state.current
                if question is None or (
                    question_id is not None and question.id != str(question_id)
                ):
                    raise Conflict(
                        "question-not-current", "That question isn't the one being asked"
                    )
                started = speech.started_at or question.asked_at
                timing = Speech(started, speech.ended_at, speech.confidence)
                expected = row.state_seq
                now = self._clock()
                analysed: Analysed | None = None
                if self._engine.needs_analysis(state, text):
                    analysed = await self._analyzer.analyze(
                        interview.organization_id, interview.id, question, text
                    )
                plan = self._engine.follow_up_plan(state, analysed, now)
                phrased = (
                    await self._follow_ups.phrase(
                        interview.organization_id, interview.id, question, text, plan
                    )
                    if plan is not None
                    else None
                )
                try:
                    turn = self._engine.answer(
                        state,
                        text,
                        now,
                        analysed=analysed,
                        follow_up_text=phrased,
                        acknowledged=acknowledged,
                    )
                except EngineError as error:
                    raise Conflict(error.code, str(error)) from error
                try:
                    async with self._db.tenant(organization_id) as session:
                        interview, row = await self._locked(session, interview_id)
                        seq = await self._apply(
                            session,
                            interview,
                            row,
                            state,
                            turn,
                            now,
                            by=by,
                            expected_seq=expected,
                            candidate=(text, question.id, timing, mode),
                        )
                except Conflict as error:
                    if error.code == "state-conflict" and attempt == 1:
                        continue
                    raise
                result = await self._result(interview, row, state, turn, now, seq)
                done = (state, turn, now, (text, question.id, timing, mode))
                break
            else:
                raise Conflict("state-conflict", "The interview moved on; try again")
        state, turn, now, answered = done
        await self._publish(interview_id, state, turn, now, answered=answered)
        return result

    async def control(
        self, organization_id: UUID, interview_id: UUID, action: Control, *, by: By
    ) -> TurnResult:
        """`repeat` or `need_a_moment`: spoken, transcribed, nothing else changes."""
        now = self._clock()
        async with self._turn(interview_id):
            interview, row, state = await self._checkpoint(organization_id, interview_id)
            expected = row.state_seq
            try:
                turn = self._engine.control(state, action, now)
            except EngineError as error:
                raise Conflict(error.code, str(error)) from error
            async with self._db.tenant(organization_id) as session:
                interview, row = await self._locked(session, interview_id)
                seq = await self._apply(
                    session, interview, row, state, turn, now, by=by, expected_seq=expected
                )
            result = await self._result(interview, row, state, turn, now, seq)
        await self._publish(interview_id, state, turn, now)
        return result

    async def tick(self, organization_id: UUID, interview_id: UUID, *, by: By) -> TurnResult | None:
        """Acts on the clock when it's due (time up, a question over its limit); else None."""
        now = self._clock()
        async with self._turn(interview_id):
            interview, row, state = await self._checkpoint(organization_id, interview_id)
            expected = row.state_seq
            if not self._engine.due(state, now):
                return None
            turn = self._engine.tick(state, now)
            async with self._db.tenant(organization_id) as session:
                interview, row = await self._locked(session, interview_id)
                seq = await self._apply(
                    session, interview, row, state, turn, now, by=by, expected_seq=expected
                )
            result = await self._result(interview, row, state, turn, now, seq)
        await self._publish(interview_id, state, turn, now)
        return result

    async def complete(
        self, organization_id: UUID, interview_id: UUID, reason: str, *, by: By
    ) -> str:
        """Ends the interview (`finished` or `candidate_ended`); a no-op once it has ended."""
        now = self._clock()
        async with self._turn(interview_id):
            async with self._db.tenant(organization_id) as session:
                interview, row = await self._load(session, interview_id, lock=True)
                if interview.status in ("completed", "evaluating", "evaluated"):
                    return interview.status
                if interview.status not in ("in_progress", "interrupted") or row is None:
                    raise Conflict(
                        "interview-not-in-progress", f"The interview is {interview.status}"
                    )
                state = InterviewState.from_json(row.state)
                state.clock.resume(now, extend=False)
                turn = self._engine.finish(state, now, reason)
                seq = await self._apply(
                    session, interview, row, state, turn, now, by=by, expected_seq=row.state_seq
                )
                status = interview.status
            await self._remember(interview_id, turn, seq)
        await self._publish(interview_id, state, turn, now)
        return status

    async def interrupt(
        self,
        organization_id: UUID,
        interview_id: UUID,
        *,
        reason: str,
        by: By,
        observed_at: datetime | None = None,
    ) -> bool:
        """The candidate dropped out: pause the interview under its resume policy. False when
        there was nothing to interrupt, or when the departure (`observed_at`) is older than the
        candidate's latest start or reconnect."""
        now = self._clock()
        async with self._turn(interview_id):
            async with self._db.tenant(organization_id) as session:
                interview, row = await self._load(session, interview_id, lock=True)
                if interview.status != "in_progress" or row is None:
                    return False
                # LiveKit stamps events to the second: only a departure from an earlier second
                # than the latest connection is stale (the presence check covers the rest).
                if (
                    observed_at is not None
                    and row.connected_at is not None
                    and observed_at < row.connected_at.replace(microsecond=0)
                ):
                    return False
                state = InterviewState.from_json(row.state)
                if state.ended:
                    return False
                if resume_policy(interview.policy).pause_timer:
                    state.clock.pause(now)
                row.interruptions += 1
                interview.interrupted_at = now
                await transition(
                    session,
                    interview,
                    "interrupted",
                    "interrupted",
                    by,
                    reason=reason,
                    details={"interruptions": row.interruptions},
                    now=now,
                )
                seq = await self._apply(
                    session, interview, row, state, Turn(), now, by=by, expected_seq=row.state_seq
                )
            await self._remember(interview_id, None, seq)
            await self.set_voice(interview_id, "paused")
        return True

    async def redispatch(self, organization_id: UUID, interview_id: UUID) -> bool:
        """Sends another agent when the last one left an interview that's still running in voice
        mode (it crashed); the new one waits for the agent lock and resumes from the
        checkpoint. False when there was nothing to do."""
        if self._media is None:
            return False
        async with self._db.tenant(organization_id) as session:
            interview, row = await self._load(session, interview_id)
            if interview.status != "in_progress" or row is None or not row.state:
                return False
            state = InterviewState.from_json(row.state)
            if state.ended or state.answer_mode != "voice":
                return False
        try:
            dispatch = await self._media.dispatch_agent(interview_id, organization_id)
        except MediaError:
            log.exception("Couldn't send another agent to interview %s", interview_id)
            return False
        async with self._db.tenant(organization_id) as session:
            interview, row = await self._load(session, interview_id, lock=True)
            if row is not None:
                row.agent_dispatch_id = dispatch
            await record_event(
                session,
                interview,
                "agent.redispatched",
                By.system(),
                from_status=interview.status,
                details={"dispatch_id": dispatch},
            )
        return True

    async def candidate_speaking(self, interview_id: UUID, speaking: bool) -> None:
        """§91's CANDIDATE_SPEAKING, from the agent's voice activity."""
        try:
            await realtime.publish(
                self._redis, interview_id, "CANDIDATE_SPEAKING", {"speaking": speaking}
            )
        except Exception:
            log.exception("Couldn't publish CANDIDATE_SPEAKING for interview %s", interview_id)

    async def workspace(
        self,
        organization_id: UUID,
        interview_id: UUID,
        question_id: UUID,
        *,
        kind: Literal["code", "whiteboard"],
        language: str | None,
        content: str,
    ) -> WorkspaceSnapshot:
        size = len(content.encode("utf-8"))
        if size > WORKSPACE_MAX_BYTES:
            raise TooLarge("workspace-too-large", "The workspace is over 256 KB")
        async with self._db.tenant(organization_id) as session:
            interview, _ = await self._load(session, interview_id)
            if interview.status not in ("in_progress", "interrupted"):
                raise Conflict("interview-not-in-progress", f"The interview is {interview.status}")
            question = await session.get(InterviewQuestion, question_id)
            if question is None or question.interview_id != interview_id:
                raise NotFound("question-not-found", "No such question in this interview")
            snapshot = WorkspaceSnapshot(
                organization_id=organization_id,
                interview_id=interview_id,
                question_id=question_id,
                kind=kind,
                language=(language or "").lower()[:20] or None,
                content=content,
                size=size,
            )
            session.add(snapshot)
            await session.flush()
            return snapshot

    async def note_proctor_event(
        self, organization_id: UUID, interview_id: UUID, kind: str, severity: str
    ) -> None:
        """SP-14's hook into §34's proctor summary; a CRITICAL event can make the AI remind the
        candidate at the next turn, when the policy says so."""
        async with self._turn(interview_id), self._db.tenant(organization_id) as session:
            interview, row = await self._load(session, interview_id, lock=True)
            if row is None or interview.status != "in_progress":
                return
            state = InterviewState.from_json(row.state)
            remind = bool((interview.policy or {}).get("remind_on_critical", True))
            self._engine.note_proctor_event(state, kind, severity, remind=remind)
            await self._apply(
                session,
                interview,
                row,
                state,
                Turn(),
                self._clock(),
                by=By.system(),
                expected_seq=row.state_seq,
            )


async def abandon(session: AsyncSession, interview: Interview, now: datetime) -> None:
    """Ends an interview interrupted for longer than its grace (the scheduler calls this, in
    the interview's tenant, with the interview locked)."""
    row = await session.get(InterviewSession, interview.id, with_for_update=True)
    await transition(
        session,
        interview,
        "abandoned",
        "abandoned",
        By.system(),
        reason="The candidate didn't come back within the resume grace period",
        now=now,
    )
    if row is not None:
        row.ended_at = now
        if row.state:
            state = InterviewState.from_json(row.state)
            state.ended_reason = "abandoned"
            state.enter("completion", now)
            row.state = state.to_json()
            row.state_seq += 1
    if await session.get(Transcript, interview.id) is None:
        session.add(
            Transcript(organization_id=interview.organization_id, interview_id=interview.id)
        )
    await session.flush()


class MediaUnavailable(Exception):
    """The media server couldn't be reached; the API answers 503."""


async def third_eye_paired(session: AsyncSession, interview: Interview) -> bool:
    """Whether a phone is paired as the third camera. SP-13 adds pairing; until then a required
    third eye can only be met with the `third_eye_waiver` accommodation."""
    return False
