"""ContextBuilder (PRD §34, master plan §6.8): everything the engine plans from, read once when
the interview starts. Resume evidence, the JD's skills, the pinned template version's settings
(the interview's policy snapshot), the question library and the organisation's FAQ.

This is the engine's only component that reads the database; the rest work on the
`InterviewContext` it returns.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.engine.state import CandidateInfo, JobInfo
from hirevion_core.models import (
    Candidate,
    CandidateAccount,
    Interview,
    Job,
    JobSkill,
    Organization,
    OrganizationSettings,
    Question,
    QuestionVersion,
)

LIBRARY_PER_SKILL = 60


@dataclass(frozen=True, slots=True)
class LibraryQuestion:
    question_id: UUID
    version: int
    text: str
    skill_name: str
    difficulty: str
    type: str
    topic: str | None = None
    expected_concepts: Sequence[str] = ()
    rubric: Sequence[dict[str, Any]] = ()
    time_limit_seconds: int | None = None
    follow_up_rules: Sequence[dict[str, Any]] = ()
    coding: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class JobSkillInfo:
    name: str
    importance: str


@dataclass(frozen=True, slots=True)
class FaqEntry:
    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class InterviewContext:
    interview_id: UUID
    organization_id: UUID
    candidate: CandidateInfo
    job: JobInfo
    duration_minutes: int
    policy: dict[str, Any]
    job_skills: Sequence[JobSkillInfo] = ()
    profile: dict[str, Any] = field(default_factory=dict)
    pinned: Sequence[LibraryQuestion] = ()
    library: Sequence[LibraryQuestion] = ()
    faq: Sequence[FaqEntry] = ()

    @property
    def template_skills(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.policy.get("skills") or []]

    @property
    def difficulty_mix(self) -> dict[str, int]:
        mix = self.policy.get("difficulty") or {}
        return {key: int(mix.get(key, 0)) for key in ("easy", "medium", "hard")}

    @property
    def question_count(self) -> int:
        return int(self.policy.get("question_count") or max(1, len(self.template_skills)))

    @property
    def question_types(self) -> list[str]:
        return [str(t) for t in self.policy.get("question_types") or []]

    @property
    def accommodations(self) -> list[str]:
        return [str(a) for a in self.policy.get("accommodations") or []]

    @property
    def coding(self) -> dict[str, Any]:
        return dict(self.policy.get("coding") or {})


def _first_name(name: str) -> str:
    parts = name.split()
    return parts[0] if parts else "there"


def library_question(version: QuestionVersion) -> LibraryQuestion:
    return LibraryQuestion(
        question_id=version.question_id,
        version=version.version,
        text=version.text,
        skill_name=version.skill_name,
        difficulty=version.difficulty,
        type=version.type,
        topic=version.topic,
        expected_concepts=tuple(version.expected_concepts or ()),
        rubric=tuple(version.rubric or ()),
        time_limit_seconds=version.time_limit_seconds,
        follow_up_rules=tuple(version.follow_up_rules or ()),
        coding=version.coding,
    )


def faq_entries(briefing: dict[str, Any] | None) -> list[FaqEntry]:
    entries = []
    for item in (briefing or {}).get("faq") or []:
        question, answer = str(item.get("question") or ""), str(item.get("answer") or "")
        if question.strip() and answer.strip():
            entries.append(FaqEntry(question.strip(), answer.strip()))
    return entries


class ContextBuilder:
    """Reads one interview's context inside its tenant's session."""

    async def build(self, session: AsyncSession, interview: Interview) -> InterviewContext:
        job = await session.get_one(Job, interview.job_id)
        candidate = await session.get_one(Candidate, interview.candidate_id)
        organization = await session.get_one(Organization, interview.organization_id)
        account_name = await session.scalar(
            select(CandidateAccount.name).where(CandidateAccount.candidate_id == candidate.id)
        )
        job_skills = (
            await session.scalars(
                select(JobSkill).where(JobSkill.job_id == job.id).order_by(JobSkill.position)
            )
        ).all()
        briefing = await session.scalar(
            select(OrganizationSettings.interview_briefing).where(
                OrganizationSettings.organization_id == interview.organization_id
            )
        )
        policy = dict(interview.policy or {})
        pinned = await self._pinned(session, interview.questions)
        names = {str(item.get("name", "")).casefold() for item in policy.get("skills") or []}
        if policy.get("use_jd", True):
            names |= {s.name.casefold() for s in job_skills if s.importance == "required"}
        library = await self._library(session, sorted(n for n in names if n))
        profile = dict(candidate.profile or {})
        years = profile.get("total_experience_years")
        return InterviewContext(
            interview_id=interview.id,
            organization_id=interview.organization_id,
            candidate=CandidateInfo(
                id=str(candidate.id),
                first_name=_first_name(account_name or candidate.name),
                experience_years=float(years) if isinstance(years, int | float) else None,
            ),
            job=JobInfo(id=str(job.id), title=job.title, company=organization.name),
            duration_minutes=interview.duration_minutes,
            policy=policy,
            job_skills=[JobSkillInfo(s.name, s.importance) for s in job_skills],
            profile=profile if policy.get("use_resume", True) else {},
            pinned=pinned,
            library=library,
            faq=faq_entries(briefing),
        )

    async def _pinned(
        self, session: AsyncSession, refs: Sequence[dict[str, Any]]
    ) -> list[LibraryQuestion]:
        keys = [(UUID(str(r["question_id"])), int(r["version"])) for r in refs]
        if not keys:
            return []
        rows = (
            await session.scalars(
                select(QuestionVersion).where(
                    tuple_(QuestionVersion.question_id, QuestionVersion.version).in_(keys)
                )
            )
        ).all()
        found = {(row.question_id, row.version): row for row in rows}
        return [library_question(found[key]) for key in keys if key in found]

    async def _library(self, session: AsyncSession, skills: Sequence[str]) -> list[LibraryQuestion]:
        if not skills:
            return []
        current = and_(
            QuestionVersion.question_id == Question.id,
            QuestionVersion.version == Question.current_version,
        )
        rows = (
            await session.scalars(
                select(QuestionVersion)
                .select_from(Question)
                .join(QuestionVersion, current)
                .where(
                    Question.status == "approved",
                    func.lower(QuestionVersion.skill_name).in_(skills),
                )
                .order_by(QuestionVersion.question_id)
                .limit(LIBRARY_PER_SKILL * len(skills))
            )
        ).all()
        return [library_question(row) for row in rows]
