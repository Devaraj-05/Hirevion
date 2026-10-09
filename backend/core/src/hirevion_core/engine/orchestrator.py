"""The Orchestrator (PRD §34, §35; master plan §6.8): a deterministic policy over the state. It
never calls a model: the caller analyses an answer first (`AnswerAnalyzer`) and, when a targeted
follow-up wants one, has it phrased (`FollowUpGenerator.phrase`); then a step mutates the state
and returns a `Turn`: what the AI says, the question it asked, the answer to record, the
questions it closed and whether the interview is now complete.

The stages run START → INTRODUCTION → the per-skill EASY → MEDIUM → HARD ladder, with
ADAPTIVE FOLLOW-UP entered from any rung → CODING (if configured) → FINAL QUESTIONS →
COMPLETION → EVALUATION (the hand-off to SP-10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from hirevion_core.engine import faq, phrasing
from hirevion_core.engine.analysis import Analysed
from hirevion_core.engine.coding import CodingController
from hirevion_core.engine.completion import CompletionEvaluator
from hirevion_core.engine.context import FaqEntry, InterviewContext
from hirevion_core.engine.difficulty import DifficultyController
from hirevion_core.engine.followups import FollowUpGenerator, FollowUpPlan
from hirevion_core.engine.guardrails import classify, fingerprint, integrity_flags
from hirevion_core.engine.planner import QuestionPlanner, pick, seed_for
from hirevion_core.engine.skills import SkillMatrixBuilder
from hirevion_core.engine.state import (
    AskedQuestion,
    AskedSummary,
    Clock,
    CodingState,
    InterviewState,
    PoolQuestion,
    QualityMark,
    QuestionKind,
    Source,
    Stage,
    StageMark,
)
from hirevion_core.engine.timing import FINAL_MINIMUM, RESERVE, TimeController
from hirevion_core.ids import uuid7

FAQ_LIMIT = 3
RUNG_STAGES: dict[str, Stage] = {"easy": "easy", "medium": "medium", "hard": "hard"}
MANIPULATION_LIMIT = 2


class EngineError(Exception):
    """A step that doesn't apply to the state (no question open, the interview over)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class RecordedAnswer:
    question_id: str
    text: str
    quality: str | None
    analysis: dict[str, Any]
    flags: list[str]
    late: bool


@dataclass(slots=True)
class Turn:
    say: list[str] = field(default_factory=list)
    asked: AskedQuestion | None = None
    answer: RecordedAnswer | None = None
    closed: list[tuple[str, str]] = field(default_factory=list)
    """(question id, status) for each question this step closed."""
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    """Things worth an interview event: a guardrail flag, a dropped skill, a skipped stage."""
    completed: str | None = None
    notice: dict[str, Any] | None = None

    @property
    def text(self) -> str:
        return " ".join(part for part in self.say if part)


Control = Literal["done_answering", "repeat", "need_a_moment"]


def build_state(
    context: InterviewContext,
    *,
    now: datetime,
    deadline: datetime,
    answer_mode: Literal["voice", "text"],
) -> InterviewState:
    """A new interview's state: the skill matrix and the question pool, at START."""
    skills, hooks = SkillMatrixBuilder().build(context)
    seed = seed_for(str(context.interview_id))
    coding = context.coding
    state = InterviewState(
        interview_id=str(context.interview_id),
        organization_id=str(context.organization_id),
        answer_mode=answer_mode,
        candidate=context.candidate,
        job=context.job,
        resume=hooks,
        skills=skills,
        clock=Clock(started_at=now, deadline_at=deadline),
        seed=seed,
        minutes=max(1, round((deadline - now).total_seconds() / 60)),
        adaptive_follow_ups=bool(context.policy.get("adaptive_follow_ups", True)),
        coding=CodingState(
            enabled=bool(coding.get("enabled")),
            status="pending" if coding.get("enabled") else "none",
            languages=[str(lang) for lang in coding.get("languages") or []],
            minutes=int(coding.get("minutes") or 0),
        ),
        faq=[{"question": e.question, "answer": e.answer} for e in context.faq],
        stages=[StageMark(stage="start", at=now)],
    )
    state.pool = QuestionPlanner().plan(context, skills, hooks, seed)
    state.remaining_seconds = state.clock.remaining(now)
    return state


class Orchestrator:
    def __init__(self) -> None:
        self.difficulty = DifficultyController()
        self.follow_ups = FollowUpGenerator()
        self.coding = CodingController()
        self.time = TimeController()
        self.completion = CompletionEvaluator()

    # What the caller needs to know before a step.

    def needs_analysis(self, state: InterviewState, text: str) -> bool:
        question = state.current
        if question is None or question.kind not in ("main", "follow_up", "coding"):
            return False
        return classify(text) == "answer"

    def follow_up_plan(
        self, state: InterviewState, analysed: Analysed | None, now: datetime
    ) -> FollowUpPlan | None:
        question = state.current
        if question is None or analysed is None:
            return None
        analysis = analysed.analysis
        if analysis.off_topic or analysis.manipulation:
            return None
        return self.follow_ups.decide(
            state,
            question,
            analysis.quality,
            analysis.missing_concepts,
            time_ok=self.time.follow_up_fits(state, now),
        )

    def due(self, state: InterviewState, now: datetime) -> bool:
        """Whether `tick()` would act: time is up or the open question has overrun."""
        if state.ended or state.current is None:
            return False
        return self.time.remaining(state, now) <= 0 or self.time.overdue(state.current, now)

    # Steps.

    def begin(self, state: InterviewState, now: datetime) -> Turn:
        if state.stage != "start":
            raise EngineError("already-started", "The interview has already begun")
        turn = Turn()
        turn.say.append(phrasing.greeting(state, state.minutes))
        self._ask(
            state,
            turn,
            now,
            kind="introduction",
            stage="introduction",
            text=phrasing.INTRODUCTION,
            source="system",
        )
        return turn

    def answer(
        self,
        state: InterviewState,
        text: str,
        now: datetime,
        *,
        analysed: Analysed | None = None,
        follow_up_text: str | None = None,
        acknowledged: bool = False,
    ) -> Turn:
        """`acknowledged`: the agent already played a short acknowledgement while the answer was
        analysed (voice mode), so the turn doesn't start with another."""
        question = self._open(state)
        turn = Turn()
        self.time.remaining(state, now)
        intent = classify(text, final_questions=question.kind == "final")
        manipulation = intent == "manipulation" or bool(
            analysed and analysed.analysis.manipulation and question.kind != "final"
        )
        if intent == "repeat":
            turn.say.append(phrasing.repeat(question.text))
            return turn
        if intent == "moment":
            turn.say.append(phrasing.MOMENT)
            return turn
        if manipulation:
            return self._manipulation(state, turn, question, text, now)
        if question.kind == "introduction":
            self._record(turn, question, text, None, {}, [], late=False)
            self._close(state, turn, question, "answered", now)
            if not acknowledged:
                turn.say.append(phrasing.ack(state.seed + question.position))
            self._advance(state, turn, now)
            return self._with_notice(state, turn)
        if question.kind == "final":
            return self._with_notice(state, self._final(state, turn, question, text, intent, now))

        late = self.time.late(question, now)
        if intent in ("silence", "dont_know") or analysed is None:
            quality = "no_answer"
            analysis: dict[str, Any] = {"source": "guardrail", "intent": intent}
            off_topic = False
            missing: list[str] = list(question.expected_concepts)
        else:
            quality = analysed.analysis.quality
            analysis = {**analysed.analysis.model_dump(), "source": analysed.source}
            if analysed.model:
                analysis["model"] = analysed.model
            off_topic = analysed.analysis.off_topic
            missing = list(analysed.analysis.missing_concepts)
        flags = ["off_topic"] if off_topic else []
        if late:
            flags.append("late")
        if intent == "answer":
            flags += integrity_flags(text, state.answer_prints)
            state.answer_prints.append(fingerprint(text))
            for flag in flags:
                if flag in ("ai_text_suspected", "repeated_answer") and flag not in state.flags:
                    state.flags.append(flag)
        plan = None
        if quality != "no_answer":
            plan = self.follow_up_plan(state, analysed, now)
        self._record(turn, question, text, quality, analysis, flags, late=late)
        self._close(state, turn, question, "answered", now)
        self._score(state, question, quality)
        if question.kind == "coding":
            self.coding.finish(state)
        if intent == "dont_know":
            turn.say.append(phrasing.DONT_KNOW)
        elif intent == "silence":
            turn.say.append(phrasing.NO_ANSWER)
        elif off_topic:
            turn.say.append(phrasing.OFF_TOPIC)
        elif not acknowledged:
            turn.say.append(phrasing.ack(state.seed + question.position))
        if plan is not None:
            self._ask(
                state,
                turn,
                now,
                kind="follow_up",
                stage="follow_up",
                text=follow_up_text or plan.text,
                source="follow_up",
                source_ref={"rule": plan.kind} if plan.rule else {"generated": plan.kind},
                parent=question,
                missing=missing,
            )
            question.follow_ups += 1
            return self._with_notice(state, turn)
        skill = state.skill(question.skill)
        if skill is not None and skill.weak_streak >= 2 and skill.remaining > 0:
            skill.dropped = True
            turn.say.append(phrasing.SKIP_SKILL)
            turn.events.append(("skill.dropped", {"skill": skill.name, "reason": "weak_answers"}))
        self._advance(state, turn, now)
        return self._with_notice(state, turn)

    def control(self, state: InterviewState, action: Control, now: datetime) -> Turn:
        question = self._open(state)
        turn = Turn()
        if action == "repeat":
            turn.say.append(phrasing.repeat(question.text))
        elif action == "need_a_moment":
            turn.say.append(phrasing.MOMENT)
        return turn

    def tick(self, state: InterviewState, now: datetime) -> Turn:
        """Acts on the clock: the interview's time is up, or the open question overran."""
        turn = Turn()
        if state.ended:
            return turn
        if self.time.remaining(state, now) <= 0:
            self._complete(state, turn, now, "time_up")
            return turn
        question = state.current
        if question is not None and self.time.overdue(question, now):
            self._close(state, turn, question, "timed_out", now)
            turn.events.append(("question.timed_out", {"question_id": question.id}))
            if question.kind == "coding":
                self.coding.finish(state)
            if question.kind == "final":
                self._complete(state, turn, now, "finished")
                return turn
            turn.say.append(phrasing.TIMED_OUT)
            self._advance(state, turn, now)
        return self._with_notice(state, turn)

    def resume(self, state: InterviewState, now: datetime, *, recovered: bool = False) -> Turn:
        """What to say on reconnecting: a recap and the open question again. `recovered` is the
        AI's own restart (after a crash), not the candidate's."""
        turn = Turn()
        if state.ended:
            return turn
        turn.say.append(phrasing.RECOVERED if recovered else phrasing.recap(state))
        if state.current is not None:
            # The question is asked again, so its time limit starts again: time away (or the
            # AI's restart) mustn't count against the candidate.
            state.current.asked_at = now
            turn.say.append(phrasing.repeat(state.current.text))
        return turn

    def finish(self, state: InterviewState, now: datetime, reason: str) -> Turn:
        turn = Turn()
        if not state.ended:
            self._complete(state, turn, now, reason)
        return turn

    def note_proctor_event(
        self, state: InterviewState, kind: str, severity: str, *, remind: bool
    ) -> None:
        """§34's proctor summary; a CRITICAL event can make the AI remind the candidate."""
        state.proctor.counts[severity] = state.proctor.counts.get(severity, 0) + 1
        state.proctor.last_kind = kind
        if remind and severity == "critical":
            state.proctor.pending_notice = kind

    # Internals.

    def _open(self, state: InterviewState) -> AskedQuestion:
        if state.ended:
            raise EngineError("interview-ended", "The interview is over")
        if state.current is None:
            raise EngineError("no-question", "No question is open")
        return state.current

    def _with_notice(self, state: InterviewState, turn: Turn) -> Turn:
        kind = state.proctor.pending_notice
        if kind and not state.ended:
            state.proctor.pending_notice = None
            turn.say.insert(0, phrasing.proctor_reminder(kind))
            turn.notice = {"kind": kind}
        return turn

    def _ask(
        self,
        state: InterviewState,
        turn: Turn,
        now: datetime,
        *,
        kind: QuestionKind,
        stage: Stage,
        text: str,
        source: Source,
        pool: PoolQuestion | None = None,
        source_ref: dict[str, Any] | None = None,
        parent: AskedQuestion | None = None,
        prefix: str | None = None,
        missing: list[str] | None = None,
        time_limit: int | None = None,
    ) -> AskedQuestion:
        state.enter(stage, now)
        base = pool
        question = AskedQuestion(
            id=str(uuid7()),
            position=state.position,
            kind=kind,
            stage=stage,
            text=text,
            source=source,
            source_ref=dict(source_ref or (base.source_ref if base else {})),
            skill=base.skill if base else (parent.skill if parent else None),
            topic=base.topic if base else (parent.topic if parent else None),
            difficulty=base.difficulty if base else (parent.difficulty if parent else None),
            type=base.type if base else (parent.type if parent else None),
            expected_concepts=list(
                base.expected_concepts
                if base
                else (missing or (parent.expected_concepts if parent else []))
            ),
            rubric=list(base.rubric if base else []),
            time_limit_seconds=time_limit
            if time_limit is not None
            else (base.time_limit_seconds if base else None),
            follow_up_rules=list(base.follow_up_rules if base else []),
            workspace=base.workspace if base else (parent.workspace if parent else "none"),
            languages=list(base.languages if base else (parent.languages if parent else [])),
            parent_id=parent.id if parent else None,
            asked_at=now,
        )
        state.position += 1
        state.current = question
        state.questions_asked.append(
            AskedSummary(
                id=question.id, kind=kind, skill=question.skill, difficulty=question.difficulty
            )
        )
        turn.asked = question
        turn.say.append(f"{prefix} {text}" if prefix else text)
        return question

    def _record(
        self,
        turn: Turn,
        question: AskedQuestion,
        text: str,
        quality: str | None,
        analysis: dict[str, Any],
        flags: list[str],
        *,
        late: bool,
    ) -> None:
        turn.answer = RecordedAnswer(question.id, text, quality, analysis, flags, late)

    def _close(
        self, state: InterviewState, turn: Turn, question: AskedQuestion, status: str, now: datetime
    ) -> None:
        turn.closed.append((question.id, status))
        for summary in state.questions_asked:
            if summary.id == question.id:
                summary.status = status
        if state.current is not None and state.current.id == question.id:
            state.current = None

    def _score(self, state: InterviewState, question: AskedQuestion, quality: str) -> None:
        state.answer_quality.append(
            QualityMark(question_id=question.id, skill=question.skill, quality=quality)  # type: ignore[arg-type]
        )
        skill = state.skill(question.skill)
        if skill is not None:
            if question.kind == "main":
                skill.answered += 1
            skill.qualities.append(quality)
            skill.weak_streak = skill.weak_streak + 1 if quality in ("weak", "no_answer") else 0
        for topic in (question.skill, question.topic):
            if topic and topic not in state.topics_covered:
                state.topics_covered.append(topic)

    def _manipulation(
        self, state: InterviewState, turn: Turn, question: AskedQuestion, text: str, now: datetime
    ) -> Turn:
        question.attempts += 1
        if "manipulation" not in state.flags:
            state.flags.append("manipulation")
        self._record(
            turn, question, text, None, {"source": "guardrail"}, ["manipulation"], late=False
        )
        turn.events.append(
            ("guardrail.flagged", {"question_id": question.id, "kind": "manipulation"})
        )
        turn.say.append(phrasing.MANIPULATION)
        if question.attempts >= MANIPULATION_LIMIT:
            self._close(state, turn, question, "skipped", now)
            if question.kind == "final":
                self._complete(state, turn, now, "finished")
                return turn
            if question.kind in ("main", "coding"):
                self._score(state, question, "no_answer")
                if question.kind == "coding":
                    self.coding.finish(state)
            self._advance(state, turn, now)
            return turn
        turn.say.append(question.text)
        return turn

    def _final(
        self,
        state: InterviewState,
        turn: Turn,
        question: AskedQuestion,
        text: str,
        intent: str,
        now: datetime,
    ) -> Turn:
        self._record(turn, question, text, None, {"intent": intent}, [], late=False)
        self._close(state, turn, question, "answered", now)
        if intent in ("no_more", "silence", "dont_know"):
            self._complete(state, turn, now, "finished")
            return turn
        entries = [FaqEntry(e["question"], e["answer"]) for e in state.faq]
        entry = faq.match(text, entries)
        state.faq_asked += 1
        if entry is not None:
            turn.say.append(entry.answer)
            turn.events.append(("faq.answered", {"faq": entry.question}))
        else:
            turn.say.append(phrasing.FAQ_UNKNOWN)
            turn.events.append(("faq.unanswered", {"question": text[:500]}))
        remaining = self.time.remaining(state, now)
        if state.faq_asked >= FAQ_LIMIT or remaining < FINAL_MINIMUM:
            self._complete(state, turn, now, "finished")
            return turn
        self._ask(
            state,
            turn,
            now,
            kind="final",
            stage="final_questions",
            text=phrasing.FAQ_MORE,
            source="faq",
            source_ref={"matched": entry.question} if entry else {"matched": None},
        )
        return turn

    def _next_skill(self, state: InterviewState) -> Any:
        current = state.skill(state.current_topic)
        if current is not None and current.remaining > 0:
            return current
        return next((s for s in state.skills if s.remaining > 0), None)

    def _advance(self, state: InterviewState, turn: Turn, now: datetime) -> None:
        remaining = self.time.remaining(state, now)
        if remaining <= 0:
            self._complete(state, turn, now, "time_up")
            return
        if state.stage in ("introduction", "easy", "medium", "hard", "follow_up"):
            cut = self.time.shrink(state, now)
            if cut:
                turn.events.append(("plan.shortened", {"skills": cut}))
            skill = self._next_skill(state) if remaining > RESERVE else None
            if skill is None and remaining <= RESERVE:
                # Out of time for the ladder: an uncovered required skill still gets its question.
                skill = next(
                    (s for s in state.skills if s.required and not s.covered and s.remaining > 0),
                    None,
                )
            if skill is not None:
                rung = self.difficulty.next_rung(skill)
                chosen = pick(state, skill, rung)
                first = all(s.asked == 0 for s in state.skills)
                prefix = (
                    phrasing.transition(skill.name, first)
                    if skill.name != state.current_topic
                    else None
                )
                state.current_topic = skill.name
                state.difficulty = chosen.difficulty
                skill.asked += 1
                skill.rung = chosen.difficulty
                stage = RUNG_STAGES.get(chosen.difficulty, "medium")
                self._ask(
                    state,
                    turn,
                    now,
                    kind="main",
                    stage=stage,
                    text=chosen.text,
                    source=chosen.source,
                    pool=chosen,
                    prefix=prefix,
                )
                return
        if state.stage != "coding" and self.coding.due(state):
            limit = self.time.coding_limit(state, now)
            coding = self.coding.start(state) if limit is not None else None
            if coding is not None and limit is not None:
                state.current_topic = coding.skill
                turn.say.append(phrasing.CODING_INTRO)
                self._ask(
                    state,
                    turn,
                    now,
                    kind="coding",
                    stage="coding",
                    text=coding.text,
                    source=coding.source,
                    pool=coding,
                    time_limit=min(limit, coding.time_limit_seconds or limit),
                )
                return
            self.coding.skip(state)
            turn.events.append(
                (
                    "coding.skipped",
                    {"reason": "no-time" if limit is None else "no-question"},
                )
            )
        if state.stage != "final_questions" and self.time.remaining(state, now) > FINAL_MINIMUM:
            self._ask(
                state,
                turn,
                now,
                kind="final",
                stage="final_questions",
                text=phrasing.FINAL_QUESTIONS,
                source="system",
            )
            return
        self._complete(state, turn, now, "finished")

    def _complete(self, state: InterviewState, turn: Turn, now: datetime, reason: str) -> None:
        question = state.current
        if question is not None:
            self._close(state, turn, question, "skipped", now)
        state.ended_reason = reason
        state.enter("completion", now)
        turn.say.append(phrasing.closing(state, reason))
        turn.completed = reason
        state.enter("evaluation", now)
