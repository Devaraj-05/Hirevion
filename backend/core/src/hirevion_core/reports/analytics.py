"""The analytics of one interview, for the recruiter's dashboard (owner, 2026-11-21: "i need to see
the complete analytics in the recruitment dashboard for that particular candidates"; ADR-0047).

Everything here is computed from what the interview stored: its questions, the transcript's
timed segments, the evaluation's scores, and the proctoring events. PRD §59's speech measures are
signals for a reviewer, never proof of anything (§57, §59): the dashboard says so beside them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any
from uuid import UUID

from hirevion_core.engine.completion import CompletionEvaluator
from hirevion_core.engine.state import InterviewState
from hirevion_core.reports.data import InterviewData

# A wait longer than this before an answer is a long pause.
LONG_PAUSE_MS = 10_000
# Below this much speech a pace means nothing.
PACE_MIN_MS = 10_000
# Faster than anyone speaks: the stored speech times are too short (answers stored as only their
# last stretch of speech, before the agent's fix of 2026-11-21).
PACE_MAX_WPM = 300
# Hesitation sounds (PRD §59 "filler words"); a recogniser may leave some out. Phrases such as
# "you know" or "i mean" are left out: they are as often plain words ("do you know the index").
FILLERS = ("um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm")
_FILLER = re.compile(
    r"\b(" + "|".join(re.escape(f) for f in sorted(FILLERS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
# A word: a letter or digit first, then any with an apostrophe or a hyphen (a dash is no word).
_WORD = re.compile("\\w[\\w'\N{RIGHT SINGLE QUOTATION MARK}-]*")


@dataclass(frozen=True, slots=True)
class Said:
    """One transcript segment, times in milliseconds from the interview's start."""

    seq: int
    speaker: str
    text: str
    start_ms: int
    end_ms: int
    question_id: UUID | None


@dataclass(slots=True)
class Speech:
    candidate_ms: int = 0
    ai_ms: int = 0
    words: int = 0
    words_per_minute: int | None = None
    response_ms: list[int] = field(default_factory=list)
    """How long each answer waited after the interviewer stopped (0 when it began before)."""
    median_response_ms: int | None = None
    long_pauses: int = 0
    fillers: dict[str, int] = field(default_factory=dict)
    fillers_per_100_words: float | None = None
    candidate_share: float | None = None
    """The candidate's share of the time either side spoke."""
    pace_unreliable: bool = False
    """The stored speech times give an impossible pace, so none is shown."""


@dataclass(slots=True)
class QuestionTiming:
    asked_ms: int | None = None
    """When the interviewer began the question."""
    thinking_ms: int | None = None
    """From the end of the question to the start of the answer."""
    speaking_ms: int = 0
    words: int = 0


def _words(text: str) -> int:
    return len(_WORD.findall(text))


def _duration(segment: Said) -> int:
    return max(0, segment.end_ms - segment.start_ms)


def _answer_waits(said: Sequence[Said]) -> list[tuple[Said, int]]:
    """Each answer's first segment, with how long it waited after the interviewer's last one."""
    waits: list[tuple[Said, int]] = []
    previous: Said | None = None
    for segment in sorted(said, key=lambda s: s.seq):
        if segment.speaker == "candidate" and previous is not None and previous.speaker == "ai":
            waits.append((segment, max(0, segment.start_ms - previous.end_ms)))
        previous = segment
    return waits


def speech(said: Sequence[Said]) -> Speech:
    stats = Speech()
    text: list[str] = []
    for segment in said:
        if segment.speaker == "candidate":
            stats.candidate_ms += _duration(segment)
            stats.words += _words(segment.text)
            text.append(segment.text)
        elif segment.speaker == "ai":
            stats.ai_ms += _duration(segment)
    if stats.candidate_ms >= PACE_MIN_MS:
        pace = round(stats.words * 60_000 / stats.candidate_ms)
        stats.pace_unreliable = pace > PACE_MAX_WPM
        stats.words_per_minute = None if stats.pace_unreliable else pace
    stats.response_ms = [wait for _, wait in _answer_waits(said)]
    if stats.response_ms:
        stats.median_response_ms = round(median(stats.response_ms))
    stats.long_pauses = sum(1 for wait in stats.response_ms if wait > LONG_PAUSE_MS)
    for match in _FILLER.finditer(" ".join(text)):
        word = match.group(1).lower()
        stats.fillers[word] = stats.fillers.get(word, 0) + 1
    if stats.words:
        stats.fillers_per_100_words = round(sum(stats.fillers.values()) * 100 / stats.words, 1)
    spoken = stats.candidate_ms + stats.ai_ms
    if spoken:
        stats.candidate_share = round(stats.candidate_ms / spoken, 2)
    return stats


def question_timing(said: Sequence[Said]) -> dict[UUID, QuestionTiming]:
    """Per question: when it was asked, the wait before its answer, and the answer's length."""
    timing: dict[UUID, QuestionTiming] = {}
    for segment in said:
        if segment.question_id is None:
            continue
        item = timing.setdefault(segment.question_id, QuestionTiming())
        if segment.speaker == "ai" and (item.asked_ms is None or segment.start_ms < item.asked_ms):
            item.asked_ms = segment.start_ms
        elif segment.speaker == "candidate":
            item.speaking_ms += _duration(segment)
            item.words += _words(segment.text)
    for first, wait in _answer_waits(said):
        if first.question_id in timing and timing[first.question_id].thinking_ms is None:
            timing[first.question_id].thinking_ms = wait
    return timing


def _score(value: Any) -> float | None:
    return None if value is None or value.value is None else round(float(value.value), 1)


def _offset_ms(data: InterviewData, moment: Any) -> int | None:
    anchor = data.anchor
    if anchor is None or moment is None:
        return None
    return max(0, int((moment - anchor).total_seconds() * 1000))


ASKED_KINDS = ("introduction", "main", "follow_up", "coding", "final")


def skill_rows(
    coverage: Sequence[dict[str, Any]], skill_scores: dict[str, Any], questions: Sequence[Any]
) -> list[dict[str, Any]]:
    """Each skill's coverage with its score, the names compared without case (the evaluation may
    write "postgresql" where the plan says "PostgreSQL"). A skill only the evaluation scored (an
    interview without a stored plan) follows, counted from its questions."""
    by_name = {name.casefold(): value for name, value in skill_scores.items()}
    rows = [
        {**item, "score": _score(by_name.pop(item["skill"].casefold(), None))} for item in coverage
    ]
    for name, value in skill_scores.items():
        if name.casefold() not in by_name:
            continue
        mine = [q for q in questions if (q.skill or "").casefold() == name.casefold()]
        rows.append(
            {
                "skill": name,
                "required": False,
                "covered": True,
                "asked": len(mine),
                "answered": sum(1 for q in mine if q.status == "answered"),
                "planned": 0,
                "dropped": False,
                "score": _score(value),
            }
        )
    return rows


def severity_counts(events: Sequence[Any], reviews: dict[Any, Any]) -> dict[str, int]:
    """Events by severity: neither the process list (a record, not a detection) nor an event a
    reviewer dismissed counts."""
    counts = {"INFO": 0, "WARNING": 0, "CRITICAL": 0}
    for event in events:
        review = reviews.get(event.id)
        dismissed = review is not None and review.outcome in ("false_positive", "not_relevant")
        if event.event != "PROCESS_INVENTORY" and not dismissed:
            counts[event.severity] = counts.get(event.severity, 0) + 1
    return counts


def interview_analytics(data: InterviewData, *, proctoring: bool) -> dict[str, Any]:
    """The dashboard's numbers for one interview. `proctoring`: the viewer may see its events."""
    said = [
        Said(s.seq, s.speaker, s.text, s.start_ms, s.end_ms, s.question_id) for s in data.segments
    ]
    talk = speech(said)
    timing = question_timing(said)
    scores = data.scores
    questions = []
    for question in sorted(data.questions, key=lambda q: q.position):
        if question.kind not in ASKED_KINDS:
            continue
        answers = data.answers.get(question.id, [])
        when = timing.get(question.id, QuestionTiming())
        questions.append(
            {
                "id": question.id,
                "position": question.position,
                "kind": question.kind,
                "skill": question.skill,
                "difficulty": question.difficulty,
                "text": question.text,
                "status": question.status,
                "asked_ms": when.asked_ms
                if when.asked_ms is not None
                else _offset_ms(data, question.asked_at),
                "thinking_ms": when.thinking_ms,
                "speaking_ms": when.speaking_ms,
                "words": when.words,
                "quality": answers[-1].quality if answers else None,
                "score": _score(scores.questions.get(str(question.id))) if scores else None,
            }
        )
    # Coverage as the engine judges it (the transcript page's own), with each skill's score.
    state = (
        InterviewState.from_json(data.run.state)
        if data.run is not None and data.run.state
        else None
    )
    coverage = CompletionEvaluator().coverage(state) if state is not None else []
    skills = skill_rows(coverage, scores.skills if scores else {}, data.questions)
    interview = data.interview
    ended = interview.completed_at or interview.ended_at
    result: dict[str, Any] = {
        "interview_id": interview.id,
        "status": interview.status,
        "planned_minutes": interview.duration_minutes,
        "started_at": data.anchor,
        "ended_at": ended,
        "duration_ms": _offset_ms(data, ended),
        "overall": _score(scores.overall) if scores else None,
        "communication": _score(scores.communication) if scores else None,
        "questions": questions,
        "skills": skills,
        "speech": {
            "candidate_ms": talk.candidate_ms,
            "ai_ms": talk.ai_ms,
            "words": talk.words,
            "words_per_minute": talk.words_per_minute,
            "median_response_ms": talk.median_response_ms,
            "long_pauses": talk.long_pauses,
            "fillers": talk.fillers,
            "fillers_per_100_words": talk.fillers_per_100_words,
            "candidate_share": talk.candidate_share,
            "pace_unreliable": talk.pace_unreliable,
        },
        "integrity": _integrity(data) if proctoring else None,
    }
    return result


def _integrity(data: InterviewData) -> dict[str, Any]:
    counts = severity_counts(data.events, data.reviews)
    events = []
    inventory: dict[str, Any] | None = None
    for event in sorted(data.events, key=lambda e: e.started_at):
        review = data.reviews.get(event.id)
        events.append(
            {
                "id": event.id,
                "event": event.event,
                "severity": event.severity,
                "source": event.source,
                "offset_ms": _offset_ms(data, event.started_at),
                "duration_ms": event.duration_ms,
                "review": review.outcome if review is not None else None,
            }
        )
        if event.event == "PROCESS_INVENTORY" and inventory is None:
            listed = next(
                (
                    e.ref.get("processes")
                    for e in data.evidence
                    if e.proctor_event_id == event.id and e.kind == "process_metadata"
                ),
                None,
            )
            inventory = {
                "offset_ms": _offset_ms(data, event.started_at),
                "count": event.details.get("count"),
                "windows": list(event.details.get("windows") or []),
                "processes": list(listed or []),
            }
    return {"counts": counts, "events": events, "inventory": inventory}
