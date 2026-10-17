"""The coding report (PRD §47, §48): what exists of an interview's coding today.

The coding service (SP-16) will run the candidate's code against tests and grade it. Until then
there are the coding questions the interview asked and the code the candidate's editor saved, and
the report says plainly that the rest is not there yet."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from hirevion_core.models import InterviewQuestion, WorkspaceSnapshot
from hirevion_core.reports import blocks as b
from hirevion_core.reports.blocks import Block, Document, Section
from hirevion_core.reports.data import InterviewData

PENDING = (
    "Code runs, test results and coding grades arrive with the coding service (SP-16). This "
    "page shows what the interview recorded so far: the coding questions and the code the "
    "candidate saved."
)
CODE_MAX = 20_000


def _coding_questions(data: InterviewData) -> list[InterviewQuestion]:
    return [q for q in data.questions if q.workspace not in (None, "none")]


def _latest_snapshots(data: InterviewData) -> dict[UUID, WorkspaceSnapshot]:
    latest: dict[UUID, WorkspaceSnapshot] = {}
    for snapshot in data.snapshots:  # oldest first, so the last one wins
        latest[snapshot.question_id] = snapshot
    return latest


def coding_blocks(data: InterviewData) -> list[Block]:
    """The coding evaluation's place in the interview report."""
    coding = (data.interview.policy or {}).get("coding") or {}
    questions = _coding_questions(data)
    return [
        b.notice(PENDING),
        b.facts(
            [
                ("Coding in this interview", "Enabled" if coding.get("enabled") else "Not enabled"),
                ("Coding questions asked", str(len(questions))),
                ("Code snapshots saved", str(len(data.snapshots))),
                ("Test results", "Not available yet"),
                ("Coding grade", "Not available yet"),
            ]
        ),
    ]


def coding_report(data: InterviewData, *, generated_at: datetime | None = None) -> Document:
    interview = data.interview
    tz = data.timezone
    questions = _coding_questions(data)
    latest = _latest_snapshots(data)
    code_blocks: list[Block] = []
    for question in questions:
        snapshot = latest.get(question.id)
        if snapshot is not None:
            code_blocks.append(
                b.code(
                    snapshot.content[:CODE_MAX],
                    language=snapshot.language,
                    caption=(
                        f"Question {question.position}, saved {b.when(snapshot.created_at, tz)}"
                    ),
                )
            )
    sections: list[Section] = [
        b.section(
            "coding_summary",
            "Coding summary",
            coding_blocks(data),
            pending=True,
            note="The coding service (SP-16) is not built yet.",
        ),
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
            "submitted_code",
            "Code the candidate saved",
            code_blocks,
            note=None if code_blocks else "No code was saved.",
        ),
        b.section(
            "test_results",
            "Test results",
            [b.notice("Test results arrive with the coding service (SP-16).")],
            pending=True,
        ),
        b.section(
            "coding_grade",
            "Coding evaluation",
            [b.notice("The coding grade arrives with the coding service (SP-16).")],
            pending=True,
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
