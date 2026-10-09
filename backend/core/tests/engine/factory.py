"""Synthetic interview contexts for the engine's tests: no database, no names that are real."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from hirevion_core.engine.context import FaqEntry, InterviewContext, JobSkillInfo, LibraryQuestion
from hirevion_core.engine.orchestrator import build_state
from hirevion_core.engine.state import CandidateInfo, InterviewState, JobInfo

NOW = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
INTERVIEW_ID = UUID("01920000-0000-7000-8000-000000000001")

PROFILE: dict[str, Any] = {
    "total_experience_years": 5,
    "projects": [
        {
            "name": "Payments gateway",
            "description": "Built FastAPI microservices for card payments.",
            "quote": "Built FastAPI microservices handling 2,000 payments a minute",
            "page": 1,
            "section": "projects",
        }
    ],
    "positions": [
        {
            "title": "Backend Engineer",
            "company": "Globex Labs",
            "quote": "Tuned PostgreSQL queries and indexes for the reporting service",
            "page": 1,
            "section": "experience",
        }
    ],
    "skills": [{"name": "Redis", "quote": "Redis", "page": 2, "section": "skills"}],
}


def library(
    skill: str,
    difficulty: str,
    text: str,
    *,
    concepts: Sequence[str] = (),
    type: str = "technical",
    rules: Sequence[dict[str, Any]] = (),
    time_limit: int | None = None,
    coding: dict[str, Any] | None = None,
) -> LibraryQuestion:
    return LibraryQuestion(
        question_id=uuid4(),
        version=1,
        text=text,
        skill_name=skill,
        difficulty=difficulty,
        type=type,
        topic=f"{skill} basics",
        expected_concepts=tuple(concepts),
        follow_up_rules=tuple(rules),
        time_limit_seconds=time_limit,
        coding=coding,
    )


POOL_TEXT = "Explain how a connection pool works and what happens when it is exhausted?"
CONCEPTS = ("reuse connections", "maximum pool size", "wait timeout")


def default_library() -> list[LibraryQuestion]:
    questions = []
    for skill in ("Python", "PostgreSQL"):
        for difficulty in ("easy", "medium", "hard"):
            for n in range(3):
                questions.append(
                    library(
                        skill,
                        difficulty,
                        f"{skill} {difficulty} question {n}: {POOL_TEXT}",
                        concepts=CONCEPTS,
                    )
                )
    return questions


def make_context(
    *,
    skills: Sequence[tuple[str, int]] = (("Python", 60), ("PostgreSQL", 40)),
    job_skills: Sequence[tuple[str, str]] = (("Python", "required"), ("PostgreSQL", "required")),
    question_count: int = 6,
    mix: dict[str, int] | None = None,
    types: Sequence[str] = ("technical", "conceptual", "resume_based", "project_based"),
    profile: dict[str, Any] | None = None,
    pinned: Sequence[LibraryQuestion] = (),
    questions: Sequence[LibraryQuestion] | None = None,
    faq: Sequence[tuple[str, str]] = (),
    coding: dict[str, Any] | None = None,
    adaptive: bool = True,
    use_resume: bool = True,
    use_jd: bool = True,
    minutes: int = 45,
) -> InterviewContext:
    return InterviewContext(
        interview_id=INTERVIEW_ID,
        organization_id=UUID("01920000-0000-7000-8000-0000000000aa"),
        candidate=CandidateInfo(id=str(uuid4()), first_name="Asha", experience_years=5),
        job=JobInfo(id=str(uuid4()), title="Backend Engineer", company="Acme"),
        duration_minutes=minutes,
        policy={
            "skills": [{"name": n, "weight": w} for n, w in skills],
            "difficulty": mix or {"easy": 20, "medium": 50, "hard": 30},
            "question_count": question_count,
            "question_types": list(types),
            "use_resume": use_resume,
            "use_jd": use_jd,
            "adaptive_follow_ups": adaptive,
            "coding": coding or {"enabled": False, "languages": ["python"], "minutes": 20},
        },
        job_skills=[JobSkillInfo(n, i) for n, i in job_skills],
        profile=profile if profile is not None else {},
        pinned=list(pinned),
        library=list(questions) if questions is not None else default_library(),
        faq=[FaqEntry(q, a) for q, a in faq],
    )


def make_state(
    context: InterviewContext | None = None, *, minutes: int = 45, **kw: Any
) -> InterviewState:
    ctx = context or make_context(minutes=minutes, **kw)
    return build_state(ctx, now=NOW, deadline=NOW + timedelta(minutes=minutes), answer_mode="voice")


STRONG = (
    "A pool keeps a set of open connections so the service can reuse connections instead of "
    "opening one per request. It has a maximum pool size, and when every connection is busy a "
    "caller waits up to a wait timeout before it gets an error, so you size the pool against "
    "the database's limits and watch the queue."
)
PARTIAL = (
    "The pool lets you reuse connections so each request does not pay for a new one, which "
    "makes things a lot faster under load."
)
WEAK = "It is something for the database, I think it makes things faster maybe."
