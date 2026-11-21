"""A synthetic interview to simulate: a job with required skills, a candidate whose resume
mentions one of them, an approved question library with expected concepts, the organisation's
FAQ, an invited interview with the text-answers accommodation approved, and the candidate's
password. Rows the application role can't create (jobs, the library) are written as the admin
role, the way the tests' fixtures do; the interview itself goes through `assignment.assign`.
Development and CI only."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.scope import ResourceScope
from hirevion_core.db.session import Database
from hirevion_core.identity.passwords import hash_password
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.interview_session import preparation
from hirevion_core.interviews import assignment
from hirevion_core.interviews.assignment import Assignment
from hirevion_core.interviews.lifecycle import By
from hirevion_core.interviews.templates import BUILT_IN_DEFAULTS
from hirevion_core.models import CandidateAccount, Interview
from hirevion_interview_simulator.coding import (
    CODING_CONCEPTS,
    CODING_LANGUAGES,
    CODING_QUESTION,
    CODING_SKILL,
    STARTER_CODE,
)

SKILLS = (("Python", 50, "required"), ("PostgreSQL", 30, "required"), ("Redis", 20, "preferred"))
LIBRARY: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {
    "Python": {
        "easy": (
            "What is the difference between a list and a tuple in Python?",
            ("mutable", "immutable", "hashable"),
        ),
        "medium": (
            "How does Python's garbage collector deal with reference cycles?",
            ("reference counting", "cycle detector", "generations"),
        ),
        "hard": (
            "How would you speed up a CPU-bound Python service that is limited by the GIL?",
            ("multiprocessing", "native extensions", "profiling"),
        ),
    },
    "PostgreSQL": {
        "easy": (
            "What does an index do in PostgreSQL, and what does it cost?",
            ("faster reads", "slower writes", "disk space"),
        ),
        "medium": (
            "How do you find out why a PostgreSQL query is slow?",
            ("explain analyze", "sequential scan", "statistics"),
        ),
        "hard": (
            "How does PostgreSQL keep concurrent transactions from seeing each other's changes?",
            ("mvcc", "snapshot", "vacuum"),
        ),
    },
    "Redis": {
        "easy": (
            "What would you use Redis for in a web application?",
            ("caching", "expiry", "in memory"),
        ),
        "medium": (
            "How do you keep a Redis cache consistent with the database?",
            ("invalidation", "ttl", "write through"),
        ),
        "hard": (
            "What happens to a Redis-backed system when Redis restarts, and how do you prepare?",
            ("persistence", "warm up", "fallback"),
        ),
    },
}
FAQ = (
    (
        "When will I hear back about the result?",
        "The team usually replies within five working days.",
    ),
    ("Is the role remote?", "It is hybrid: three days a week in the Bengaluru office."),
)
PROFILE = {
    "total_experience_years": 5,
    "projects": [
        {
            "name": "Ledger service",
            "description": "Moved reporting queries to PostgreSQL read replicas.",
            "quote": "Moved reporting queries to PostgreSQL read replicas and cut p95 by 60%",
            "page": 1,
            "section": "projects",
        }
    ],
}


@dataclass
class Seeded:
    organization_id: UUID
    interview_id: UUID
    email: str
    password: str
    knowledge: dict[str, list[str]] = field(default_factory=dict)


async def _seeded(conn: Any, organization_id: UUID, question: str, skill: str) -> bool:
    """Whether the organisation's library already holds `question` for `skill`."""
    found = await conn.scalar(
        text(
            "SELECT q.id FROM questions q JOIN question_versions v "
            "ON v.question_id = q.id AND v.organization_id = q.organization_id "
            "WHERE q.organization_id = :org AND q.status = 'approved' "
            "AND v.text = :text AND v.skill_name = :skill LIMIT 1"
        ),
        {"org": organization_id, "text": question, "skill": skill},
    )
    return found is not None


async def _library(conn: Any, organization_id: UUID) -> dict[str, list[str]]:
    """The simulator's library, inserted once per organisation: each seeded interview used to add
    another copy of every question (13 by the owner's run of 2026-11-21)."""
    knowledge: dict[str, list[str]] = {}
    for skill, rungs in LIBRARY.items():
        for difficulty, (question, concepts) in rungs.items():
            knowledge[question] = list(concepts)
            if await _seeded(conn, organization_id, question, skill):
                continue
            question_id = uuid7()
            await conn.execute(
                text(
                    "INSERT INTO questions (id, organization_id, category, status, source) "
                    "VALUES (:id, :org, 'technical', 'approved', 'manual')"
                ),
                {"id": question_id, "org": organization_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO question_versions (organization_id, question_id, version, text, "
                    "skill_name, topic, difficulty, type, expected_concepts, follow_up_rules) "
                    "VALUES (:org, :id, 1, :text, :skill, :topic, :difficulty, 'technical', "
                    ":concepts, :rules)"
                ),
                {
                    "org": organization_id,
                    "id": question_id,
                    "text": question,
                    "skill": skill,
                    "topic": f"{skill} {difficulty}",
                    "difficulty": difficulty,
                    "concepts": list(concepts),
                    "rules": json.dumps(
                        [{"when": "weak", "prompt": f"What do you know about {concepts[0]}?"}]
                    ),
                },
            )
    return knowledge


async def _coding_question(conn: Any, organization_id: UUID) -> None:
    """The coding question the simulator's interviews ask when coding is on (SP-16), once."""
    if await _seeded(conn, organization_id, CODING_QUESTION, CODING_SKILL):
        return
    question_id = uuid7()
    await conn.execute(
        text(
            "INSERT INTO questions (id, organization_id, category, status, source) "
            "VALUES (:id, :org, 'coding', 'approved', 'manual')"
        ),
        {"id": question_id, "org": organization_id},
    )
    await conn.execute(
        text(
            "INSERT INTO question_versions (organization_id, question_id, version, text, "
            "skill_name, topic, difficulty, type, expected_concepts, time_limit_seconds, coding) "
            "VALUES (:org, :id, 1, :text, :skill, 'Coding', 'medium', 'coding', :concepts, 600, "
            ":coding)"
        ),
        {
            "org": organization_id,
            "id": question_id,
            "text": CODING_QUESTION,
            "skill": CODING_SKILL,
            "concepts": list(CODING_CONCEPTS),
            "coding": json.dumps(
                {"languages": list(CODING_LANGUAGES), "starter_code": STARTER_CODE}
            ),
        },
    )


async def seed_interview(
    admin: AsyncEngine,
    app_db: Database,
    organization_id: UUID,
    recruiter_id: UUID,
    *,
    password: str,
    settings: IdentitySettings,
    text_answers: bool = True,
    duration_minutes: int = 30,
    coding: bool = False,
) -> Seeded:
    """`coding`: the template has coding on and the library a coding question (SP-16)."""
    job_id, candidate_id, application_id, template_id = uuid7(), uuid7(), uuid7(), uuid7()
    email = f"sim-{candidate_id.hex[-10:]}@example.test"
    async with admin.begin() as conn:
        number = await conn.scalar(
            text("SELECT coalesce(max(number), 0) + 1 FROM jobs WHERE organization_id = :o"),
            {"o": organization_id},
        )
        await conn.execute(
            text(
                "INSERT INTO jobs (id, organization_id, number, title, status, recruiter_id) "
                "VALUES (:id, :org, :number, 'Backend Engineer (simulated)', 'open', :recruiter)"
            ),
            {"id": job_id, "org": organization_id, "number": number, "recruiter": recruiter_id},
        )
        for position, (skill, _, importance) in enumerate(SKILLS):
            await conn.execute(
                text(
                    "INSERT INTO job_skills (organization_id, job_id, position, name, importance) "
                    "VALUES (:org, :job, :position, :name, :importance)"
                ),
                {
                    "org": organization_id,
                    "job": job_id,
                    "position": position,
                    "name": skill,
                    "importance": importance,
                },
            )
        await conn.execute(
            text(
                "INSERT INTO candidates (id, organization_id, name, email, profile) "
                "VALUES (:id, :org, 'Sim Candidate', :email, :profile)"
            ),
            {
                "id": candidate_id,
                "org": organization_id,
                "email": email,
                "profile": json.dumps(PROFILE),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO applications (id, organization_id, candidate_id, job_id, stage) "
                "VALUES (:id, :org, :candidate, :job, 'shortlisted')"
            ),
            {
                "id": application_id,
                "org": organization_id,
                "candidate": candidate_id,
                "job": job_id,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO interview_templates (id, organization_id, name) "
                "VALUES (:id, :org, :name)"
            ),
            {
                "id": template_id,
                "org": organization_id,
                "name": f"Simulated {template_id.hex[-8:]}",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO interview_template_versions (organization_id, template_id, version, "
                "name, duration_minutes, question_count, skills, difficulty, question_types, "
                "coding, recording, rubric) VALUES (:org, :id, 1, 'Simulated', :minutes, 6, "
                ":skills, :difficulty, ARRAY['technical','conceptual','resume_based'], :coding, "
                ":recording, :rubric)"
            ),
            {
                "org": organization_id,
                "id": template_id,
                "minutes": duration_minutes,
                "skills": json.dumps(
                    [{"name": s, "skill_id": None, "weight": w} for s, w, _ in SKILLS]
                ),
                "difficulty": json.dumps({"easy": 34, "medium": 33, "hard": 33}),
                "coding": json.dumps(
                    {"enabled": True, "languages": list(CODING_LANGUAGES), "minutes": 10}
                    if coding
                    else {"enabled": False, "languages": ["python"], "minutes": 20}
                ),
                "recording": json.dumps({"screen": True, "camera": True, "audio": True}),
                "rubric": json.dumps(BUILT_IN_DEFAULTS["rubric"]),
            },
        )
        knowledge = await _library(conn, organization_id)
        if coding:
            await _coding_question(conn, organization_id)
        # Adds the simulator's FAQ to whatever the organisation already has.
        saved = await conn.scalar(
            text(
                "SELECT interview_briefing FROM organization_settings WHERE organization_id = :org"
            ),
            {"org": organization_id},
        )
        briefing = dict(saved or {})
        faq = list(briefing.get("faq") or [])
        asked = {str(item.get("question", "")).casefold() for item in faq}
        faq += [{"question": q, "answer": a} for q, a in FAQ if q.casefold() not in asked]
        briefing = {"instructions": list(briefing.get("instructions") or []), "faq": faq}
        await conn.execute(
            text(
                "INSERT INTO organization_settings (organization_id, interview_briefing) "
                "VALUES (:org, :briefing) ON CONFLICT (organization_id) "
                "DO UPDATE SET interview_briefing = excluded.interview_briefing"
            ),
            {"org": organization_id, "briefing": json.dumps(briefing)},
        )

    actor = Actor(recruiter_id, organization_id, frozenset(permissions_for(["recruiter"])))
    now = datetime.now(UTC)
    async with app_db.tenant(organization_id) as session:
        result = await assignment.assign(
            session,
            actor,
            Assignment(
                application_ids=[application_id],
                template_id=template_id,
                starts_at=now - timedelta(minutes=5),
                expires_at=now + timedelta(days=1),
            ),
            ResourceScope(recruiter_id, organization_wide=True, team_ids=frozenset()),
            settings=settings,
        )
        if not result.created:
            raise RuntimeError(f"couldn't assign the interview: {result.skipped}")
        interview = result.created[0]
        if text_answers:
            locked = await session.get_one(Interview, interview.id)
            request = await preparation.request_accommodation(
                session,
                locked,
                ["text_answers"],
                "Simulated candidate",
                By("candidate", "simulator"),
            )
            await preparation.decide_accommodation(
                session, actor, locked, request.id, approved=["text_answers"], note="simulator"
            )
        account_id = await session.scalar(
            select(CandidateAccount.id).where(CandidateAccount.candidate_id == candidate_id)
        )
    async with admin.begin() as conn:
        await conn.execute(
            text(
                "UPDATE candidate_accounts SET status = 'active', password_hash = :hash "
                "WHERE id = :id"
            ),
            {"hash": hash_password(password), "id": account_id},
        )
        await conn.execute(
            text(
                "INSERT INTO organization_settings (organization_id, candidate_access) "
                "VALUES (:org, '{\"new_device_otp\": false}') ON CONFLICT (organization_id) "
                "DO UPDATE SET candidate_access = excluded.candidate_access"
            ),
            {"org": organization_id},
        )
    return Seeded(organization_id, interview.id, email, password, knowledge)


class NotSeeded(Exception):
    """The development organisation or its recruiter doesn't exist yet (`hv seed-identity`)."""


async def seed_development_interview(
    *, text_answers: bool, password: str, coding: bool = False
) -> Seeded:
    """A synthetic interview in the development organisation, for its seeded recruiter
    (with a coding question when `coding`, SP-16)."""
    from hirevion_core.db.session import create_database
    from hirevion_core.identity.bootstrap import SEED_ORGANIZATION_SLUG, seed_email
    from hirevion_core.identity.settings import load_identity_settings
    from hirevion_core.models import Organization, User
    from hirevion_core.settings import load_core_settings

    core = load_core_settings()
    admin, app_db = create_database(core, "admin"), create_database(core, "app")
    try:
        async with admin.unscoped() as session:
            organization_id = await session.scalar(
                select(Organization.id).where(Organization.slug == SEED_ORGANIZATION_SLUG)
            )
            recruiter_id = await session.scalar(
                select(User.id).where(User.email == seed_email("recruiter"))
            )
        if organization_id is None or recruiter_id is None:
            raise NotSeeded
        return await seed_interview(
            admin.engine,
            app_db,
            organization_id,
            recruiter_id,
            password=password,
            settings=load_identity_settings(),
            text_answers=text_answers,
            coding=coding,
            duration_minutes=45 if coding else 30,
        )
    finally:
        await app_db.dispose()
        await admin.dispose()
