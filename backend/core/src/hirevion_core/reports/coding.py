"""The coding report (PRD §47, §48; SP-16, ADR-0033): each coding question, the final code and every
submission, the AI's review of the code with its evidence, and the console's integrity signals.

The code was typed in a plain text console and never run: there are no test results or measured
times. The review read the code; its complexity figures are estimates, and the integrity signals
are for a reviewer to weigh, never proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from hirevion_core.coding.final import FinalCode, final_codes
from hirevion_core.coding.signals import Event, IntegritySignals, integrity_signals
from hirevion_core.models import InterviewQuestion
from hirevion_core.reports import blocks as b
from hirevion_core.reports.blocks import Block, Document, Section
from hirevion_core.reports.data import InterviewData

METHOD = (
    "The candidate typed the code in a plain text box and submitted it. It was never run: there "
    "are no test results. The AI reviewed it after the interview by reading it, and every score "
    "cites lines of the code. Time and space complexity are the reviewer's estimates."
)
SIGNALS_NOTE = (
    "Integrity signals describe what happened in the code box. They are for a reviewer to weigh, "
    "never proof: pasting from one's own notes or leaving the box to re-read the question is "
    "ordinary."
)
CODE_MAX = 20_000
CRITERIA_LABELS = {
    "correctness": "Correctness",
    "approach": "Approach",
    "edge_cases": "Edge cases",
    "time_complexity": "Time complexity (estimated)",
    "space_complexity": "Space complexity (estimated)",
    "code_quality": "Code quality",
    "readability": "Readability",
}
SOURCE_LABELS = {
    "submitted": "submitted by the candidate",
    "time_limit": "kept when the time ran out",
    "closed": "kept when the question ended",
    "snapshot": "the last saved text",
    "none": "nothing was typed",
}


def coding_questions(data: InterviewData) -> list[InterviewQuestion]:
    return [q for q in data.questions if q.kind == "coding"]


def finals(data: InterviewData) -> dict[UUID, FinalCode]:
    """Each coding question's final code, as the evaluator reviewed it."""
    return final_codes(data.submissions, data.snapshots)


def review(data: InterviewData) -> Mapping[str, Any]:
    """The evaluation's coding entry (empty before the interview is evaluated)."""
    if data.evaluation is None:
        return {}
    return (data.evaluation.summary or {}).get("coding") or {}


def reviews_by_question(data: InterviewData) -> dict[str, Mapping[str, Any]]:
    return {str(q.get("question_id")): q for q in review(data).get("questions") or []}


def coding_signals(data: InterviewData) -> dict[UUID, IntegritySignals]:
    """Each coding question's integrity signals, in one pass over the console's events."""
    final = finals(data)
    events: dict[UUID, list[Event]] = {}
    for item in data.console_events:
        events.setdefault(item.question_id, []).append(
            Event(item.kind, item.occurred_at, item.chars)
        )
    signals = {}
    for question in coding_questions(data):
        code = final.get(question.id)
        end = question.closed_at or (code.at if code else None) or datetime.now(UTC)
        signals[question.id] = integrity_signals(
            events.get(question.id, []),
            final_chars=len(code.code) if code else 0,
            closed_at=end,
        )
    return signals


def signals_for(data: InterviewData, question: InterviewQuestion) -> IntegritySignals:
    return coding_signals(data)[question.id]


def question_line(item: Mapping[str, Any]) -> str | None:
    """A coding question's line in the summary: its score and the estimated time, if any."""
    if item.get("status") == "no_code":
        return "No code was given"
    if item.get("status") != "scored":
        return None
    time = ((item.get("criteria") or {}).get("time_complexity") or {}).get("estimate")
    score = b.score(item.get("score"))
    return f"{score}, estimated {time} time" if time else score


def coding_blocks(data: InterviewData) -> list[Block]:
    """The coding evaluation's place in the interview report."""
    questions = coding_questions(data)
    if not questions:
        enabled = bool(((data.interview.policy or {}).get("coding") or {}).get("enabled"))
        return [
            b.notice(
                "Coding was enabled, but no coding question was asked."
                if enabled
                else "This interview had no coding question."
            )
        ]
    slot = review(data)
    rows: list[tuple[str, str | None]] = [
        ("Coding score", b.score(slot.get("score")) if slot.get("score") is not None else None),
        ("Coding questions", str(len(questions))),
        ("Submissions", str(len(data.submissions))),
    ]
    reviewed = reviews_by_question(data)
    for question in questions:
        rows.append(
            (f"Question {question.position}", question_line(reviewed.get(str(question.id)) or {}))
        )
    return [b.notice(METHOD), b.facts(rows)]


def _assessment(data: InterviewData, questions: Sequence[InterviewQuestion]) -> list[Block]:
    reviewed = reviews_by_question(data)
    content: list[Block] = []
    for question in questions:
        item = reviewed.get(str(question.id))
        if item is None:
            continue
        content.append(b.text(f"Question {question.position}: {question.skill or 'coding'}"))
        if item.get("status") == "no_code":
            content.append(b.notice("No code was given, so there was nothing to review."))
            continue
        criteria = item.get("criteria") or {}
        content.append(
            b.table(
                f"Criteria for question {question.position}",
                ["Criterion", "Score", "Estimate", "Evidence", "Why"],
                [
                    [
                        label,
                        b.score(c.get("score")) + ("" if c.get("supported") else " *"),
                        c.get("estimate"),
                        str(len(c.get("evidence") or [])),
                        c.get("rationale"),
                    ]
                    for key, label in CRITERIA_LABELS.items()
                    if (c := criteria.get(key))
                ],
            )
        )
        quoted = [
            (
                e["quote"],
                f"{CRITERIA_LABELS[key]} · line {e['line']}"
                + (f" to {e['end_line']}" if e["end_line"] != e["line"] else ""),
            )
            for key in CRITERIA_LABELS
            for e in (criteria.get(key) or {}).get("evidence") or []
        ]
        if quoted:
            content.append(b.quotes(quoted))
        if item.get("summary"):
            content.append(b.text(str(item["summary"])))
        if item.get("edge_cases_missed"):
            content += [b.text("Edge cases the code misses"), b.bullets(item["edge_cases_missed"])]
        if item.get("unsupported"):
            content.append(
                b.text(
                    "* No verified line of code backs this score; it is capped at 5.", muted=True
                )
            )
        if "manipulation_attempt" in (item.get("flags") or []):
            content.append(
                b.notice(
                    "The code holds an instruction aimed at the reviewer; it was ignored.",
                    warning=True,
                )
            )
    return content


def coding_report(data: InterviewData, *, generated_at: datetime | None = None) -> Document:
    interview = data.interview
    tz = data.timezone
    questions = coding_questions(data)
    numbers = {q.id: q.position for q in questions}
    code_blocks = [
        b.code(
            item.code[:CODE_MAX],
            language=item.language,
            caption=(
                f"Question {numbers.get(item.question_id, '?')}, {item.language or 'text'}, "
                f"{SOURCE_LABELS.get(item.source, item.source)} {b.when(item.at, tz)}"
            ),
        )
        for item in finals(data).values()
        if item.question_id in numbers
    ]
    evaluated = data.evaluation is not None
    assessment = _assessment(data, questions)
    signal_blocks: list[Block] = []
    signals_by_question = coding_signals(data)
    for question in questions:
        signals = signals_by_question[question.id]
        signal_blocks += [
            b.text(f"Question {question.position}"),
            b.bullets(signals.statements),
            b.facts(
                [
                    ("Pastes", f"{signals.pastes} ({signals.pasted_chars} characters)"),
                    ("Left the code box", f"{signals.blurs} times, {signals.time_away_seconds} s"),
                    ("Typing", f"about {signals.typing_seconds} s"),
                ]
            ),
        ]
    if signal_blocks:
        signal_blocks.insert(0, b.notice(SIGNALS_NOTE))
    sections: list[Section] = [
        b.section("coding_summary", "Coding summary", coding_blocks(data)),
        b.section(
            "coding_questions",
            "Coding questions",
            [
                b.table(
                    "Coding questions asked",
                    ["#", "Skill", "Languages", "Time limit", "Question"],
                    [
                        [
                            str(q.position),
                            q.skill,
                            ", ".join(q.languages) or None,
                            f"{q.time_limit_seconds // 60} min" if q.time_limit_seconds else None,
                            q.text,
                        ]
                        for q in questions
                    ],
                )
            ],
            note=None if questions else "This interview asked no coding questions.",
        ),
        b.section(
            "final_code",
            "Final code",
            code_blocks,
            note=None if code_blocks else "No code was given.",
        ),
        b.section(
            "submissions",
            "Every submission",
            [
                b.table(
                    "Submissions, oldest first",
                    ["Question", "Language", "Characters", "How", "When", "SHA-256"],
                    [
                        [
                            str(numbers.get(item.question_id, "?")),
                            item.language,
                            str(item.size),
                            SOURCE_LABELS.get(item.source, item.source),
                            b.when(item.created_at, tz),
                            item.sha256[:12],
                        ]
                        for item in data.submissions
                    ],
                )
            ],
            note=None if data.submissions else "No code was submitted.",
        ),
        b.section(
            "assessment",
            "AI review of the code",
            [b.notice(METHOD), *assessment] if assessment else [],
            note=None
            if assessment
            else (
                "The interview hasn't been evaluated yet."
                if not evaluated and questions
                else "There is no code to review."
            ),
        ),
        b.section(
            "integrity",
            "Integrity signals",
            signal_blocks,
            note=None if signal_blocks else "There was no coding question.",
        ),
    ]
    return b.document(
        "coding",
        "Coding report",
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
