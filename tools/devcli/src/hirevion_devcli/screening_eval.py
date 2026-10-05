"""`hv eval-screening`: how well screening ranks the synthetic candidates (SP-05; target in
ADR-0016: NDCG@10 ≥ 0.80). It runs after `hv eval-resumes` has parsed the set into its
evaluation organisation: three jobs are built from the set's most common skills, each candidate
is labelled from their true skills (the share of the job's skills they really have), and every
candidate is screened with the configured AI. The labels never reach the AI."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from hirevion_core.access.actor import Actor
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.db.session import create_database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges, SkillInput
from hirevion_core.models import Application, Candidate, Document
from hirevion_core.screening.engine import screen_application
from hirevion_core.screening.runner import rerank
from hirevion_core.settings import load_core_settings

from .synthetic_resumes import FAMILIES

TARGET_NDCG = 0.80
K = 10
RELEVANT = 2 / 3


def ndcg_at(labels_in_ranked_order: Sequence[float], k: int = K) -> float:
    """Normalised discounted cumulative gain of a ranking, from graded labels (0 to 1)."""

    def dcg(labels: Sequence[float]) -> float:
        return sum((2**label - 1) / math.log2(index + 2) for index, label in enumerate(labels[:k]))

    ideal = dcg(sorted(labels_in_ranked_order, reverse=True))
    return dcg(labels_in_ranked_order) / ideal if ideal else 1.0


def precision_at(labels_in_ranked_order: Sequence[float], k: int = K) -> float:
    top = labels_in_ranked_order[:k]
    return sum(1 for label in top if label >= RELEVANT) / len(top) if top else 0.0


def label(truth_skills: Sequence[str], job_skills: Sequence[str]) -> float:
    have = {skill.lower() for skill in truth_skills}
    return sum(1 for skill in job_skills if skill.lower() in have) / len(job_skills)


def job_skill_sets(jobs_wanted: int = 3) -> list[list[str]]:
    """Each job asks for the first three skills of one role family (backend, frontend, data),
    so its candidates range from a full fit to none."""
    return [list(skills[:3]) for skills, _ in list(FAMILIES.values())[:jobs_wanted]]


@dataclass
class JobReport:
    skills: list[str]
    screened: int
    ndcg: float
    precision: float


@dataclass
class Report:
    jobs: list[JobReport] = field(default_factory=list)

    @property
    def ndcg(self) -> float:
        return sum(job.ndcg for job in self.jobs) / len(self.jobs) if self.jobs else 0.0

    def met(self) -> bool:
        return (
            bool(self.jobs)
            and all(job.screened for job in self.jobs)
            and (self.ndcg >= TARGET_NDCG)
        )

    def markdown(self, profile: str) -> str:
        rows = "\n".join(
            f"| {', '.join(job.skills)} | {job.screened} | {job.ndcg:.3f} | {job.precision:.2f} |"
            for job in self.jobs
        )
        when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        verdict = "met" if self.met() else "**not met**"
        return "\n".join(
            [
                "# Screening evaluation",
                "",
                f"- **Run:** {when}, AI profile `{profile}`, prompt `screening-assess-v1`.",
                f"- **Target (ADR-0016):** mean NDCG@{K} ≥ {TARGET_NDCG:.2f}: {verdict} "
                f"({self.ndcg:.3f}).",
                "- **Labels:** the share of each job's three skills a candidate truly has.",
                "",
                f"| Job skills | Screened | NDCG@{K} | Precision@{K} |",
                "|---|---|---|---|",
                rows,
                "",
            ]
        )


async def evaluate(
    truths_file: Path, *, limit: int, log: Callable[[str], None]
) -> tuple[Report, str]:
    """Screens the newest evaluation organisation's candidates for three made-up jobs."""
    truths = [line for line in truths_file.read_text(encoding="utf-8").splitlines() if line]
    by_email = {row["email"].lower(): row for row in (json.loads(line) for line in truths)}
    core = load_core_settings()
    admin, db = create_database(core, "admin"), create_database(core, "app")
    settings = load_ai_settings()
    ai = build_ai(settings, db)
    report = Report()
    try:
        async with admin.unscoped() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT o.id, u.id FROM organizations o JOIN users u "
                        "ON u.organization_id = o.id WHERE o.name = 'Resume evaluation' "
                        "ORDER BY o.created_at DESC LIMIT 1"
                    )
                )
            ).first()
        if row is None:
            raise RuntimeError("No evaluation organisation: run `uv run hv eval-resumes` first")
        org, user = UUID(str(row[0])), UUID(str(row[1]))
        actor = Actor(user, org, frozenset(permissions_for(["recruiter"])))
        async with db.tenant(org) as session:
            people = [
                (candidate, document_id)
                for candidate, document_id in (
                    await session.execute(
                        select(Candidate, Candidate.resume_document_id).where(
                            Candidate.email.is_not(None)
                        )
                    )
                ).all()
                if candidate.email and candidate.email.lower() in by_email
            ][:limit]
        if not people:
            raise RuntimeError(
                "No evaluation candidate matches the synthetic set: run `uv run hv eval-resumes`"
                " with a real AI profile first (the mock AI doesn't read resumes)"
            )
        for skills in job_skill_sets():
            async with db.tenant(org) as session:
                job = await jobs.create_job(
                    session,
                    actor,
                    JobChanges(
                        title=f"Evaluation: {', '.join(skills)}",
                        skills=[SkillInput(skill) for skill in skills],
                    ),
                )
                applications = []
                for candidate, document_id in people:
                    document = await session.get(Document, document_id) if document_id else None
                    application = Application(
                        organization_id=org,
                        candidate_id=candidate.id,
                        job_id=job.id,
                        document_id=document.id if document else None,
                        stage="parsed",
                    )
                    session.add(application)
                    applications.append((application, candidate))
                await session.flush()
                ids = [(application.id, candidate.email) for application, candidate in applications]
            log(f"Screening {len(ids)} candidates for: {', '.join(skills)}")
            for application_id, _ in ids:
                await screen_application(db, ai, org, application_id)
            async with db.tenant(org) as session:
                await rerank(session, job.id)
                ordered = (
                    await session.execute(
                        select(Application.rank, Candidate.email)
                        .join(Candidate, Candidate.id == Application.candidate_id)
                        .where(Application.job_id == job.id, Application.rank.is_not(None))
                        .order_by(Application.rank)
                    )
                ).all()
            labels = [label(by_email[str(email).lower()]["skills"], skills) for _, email in ordered]
            report.jobs.append(
                JobReport(skills, len(ordered), ndcg_at(labels), precision_at(labels))
            )
        return report, settings.profile
    finally:
        await ai.aclose()
        await db.dispose()
        await admin.dispose()
