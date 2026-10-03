"""Screening one application: the score, evidence, knock-outs, blind text and the cache
(SP-05 Task 3)."""

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from hirevion_core.access.actor import Actor
from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import ChatMessage
from hirevion_core.candidates import profiles
from hirevion_core.db.session import Database
from hirevion_core.documents.resume import ResumeResult
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges, SkillInput
from hirevion_core.models import Application, ApplicationHistory, Document, Job
from hirevion_core.screening import config
from hirevion_core.screening.engine import screen_application

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]

RESUME = (
    "Asha Rao\nasha.rao@example.test | +91 98765 43210 | Pune\n\n"
    "Summary\nBackend engineer building payment APIs.\n\n"
    "Skills\nPython, Kubernetes\n\n"
    "Experience\nSenior Backend Engineer, Acme Payments (2020 - present)\n"
    "- Built a payments gateway handling UPI transfers\n\n"
    "Education\nB.Tech, Computer Science\n\n"
    "Personal Details\nDate of Birth: 14/03/1996\nMarital Status: Married\n"
)


def factor(score: int, *quotes: str) -> dict[str, Any]:
    return {"score": score, "evidence": [{"quote": quote} for quote in quotes]}


class Recorder:
    def __init__(self, projects_quote: str = "Built a payments gateway handling UPI transfers"):
        self.sent: list[str] = []
        self.projects_quote = projects_quote

    def __call__(self, messages: Sequence[ChatMessage]) -> Any:
        self.sent.append(messages[-1]["content"])
        return {
            "roles": factor(90, "Senior Backend Engineer, Acme Payments"),
            "projects": factor(80, self.projects_quote),
            "domain": factor(70, "payment APIs"),
            "education": factor(100),
            "location": factor(100),
            "strengths": ["Payments experience"],
            "concerns": ["No Go"],
            "missing_requirements": ["Go"],
        }


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


@pytest.fixture
def ai(app_db: Database) -> AiServices:
    return build_ai(AiSettings(profile="mock"), app_db)


async def setup(app_db: Database, acme: Actor, *, years: float = 6) -> tuple[Job, Application]:
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.create_job(
            session,
            acme,
            JobChanges(
                title="Backend Engineer",
                experience_min=Decimal(4),
                skills=[
                    SkillInput("Python"),
                    SkillInput("Kubernetes", min_years=Decimal(3)),
                    SkillInput("Terraform"),
                    SkillInput("Go", "preferred"),
                ],
            ),
        )
        document = Document(
            organization_id=acme.organization_id,
            kind="resume",
            job_id=job.id,
            sha256="a" * 64,
            text=RESUME,
            status="parsed",
            created_by=acme.user_id,
        )
        session.add(document)
        await session.flush()

        def item(value: str) -> dict[str, Any]:
            return {"value": value, "quote": value, "page": 1, "section": None}

        profile = {
            "name": item("Asha Rao"),
            "email": item("asha.rao@example.test"),
            "skills": [
                {"name": "Python", "years": 6, "quote": "Python"},
                {"name": "Kubernetes", "years": 2, "quote": "Kubernetes"},
            ],
            "total_experience_years": years,
            "positions": [],
        }
        await profiles.build(
            session, document, ResumeResult(profile, 0, "fake"), flags={}, embedding=None
        )
        application = await session.scalar(select(Application))
        assert application is not None
        return job, application


async def test_an_application_is_scored_with_evidence(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    _, application = await setup(app_db, acme)
    recorder = Recorder()
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["screening.assess"] = recorder

    result = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert result is not None
    factors = result.factors
    # Python full, Kubernetes half (2 of 3 years), Terraform missing: 1.5 / 3.
    assert factors["required_skills"]["score"] == 50
    assert factors["required_skills"]["evidence"] == ["Python", "Kubernetes"]
    assert factors["preferred_skills"]["score"] == 0
    assert factors["experience"]["score"] == 97  # 0.7 * 100 + 0.3 * 90
    assert factors["projects"]["evidence"] == ["Built a payments gateway handling UPI transfers"]
    # 35*50 + 25*97 + 15*80 + 10*0 + 10*70 + 5*100 = 6575 → 66
    assert result.score == 66
    assert result.knockouts == ["Missing required skills: Terraform"]
    assert result.missing[:1] == ["Required skill: Terraform"]
    assert result.skill_match["short_on_years"] == ["Kubernetes"]

    async with app_db.tenant(acme.organization_id) as session:
        stored = await session.get_one(Application, application.id)
        assert (stored.stage, stored.screening_result_id) == ("screened", result.id)
        history = (await session.scalars(select(ApplicationHistory))).all()
        assert [(h.from_stage, h.to_stage, h.score) for h in history] == [
            ("parsed", "screened", 66)
        ]


async def test_the_ai_sees_a_blind_resume_by_default(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    _, application = await setup(app_db, acme)
    recorder = Recorder()
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["screening.assess"] = recorder
    await screen_application(app_db, ai, acme.organization_id, application.id)
    sent = recorder.sent[0]
    for hidden in ("Asha", "asha.rao@", "98765", "14/03/1996", "Married"):
        assert hidden not in sent, hidden
    assert "Senior Backend Engineer, Acme Payments" in sent


async def test_unsupported_scores_are_capped_and_results_are_reused(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    job, application = await setup(app_db, acme)
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["screening.assess"] = Recorder(projects_quote="Led a team of 40 at Google")
    first = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert first is not None
    assert first.factors["projects"] == {"score": 50, "evidence": [], "supported": False}
    calls = ai.llm.calls

    again = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert again is not None and again.id == first.id
    assert ai.llm.calls == calls

    # A new configuration version means a new result.
    async with app_db.tenant(acme.organization_id) as session:
        await config.save(session, acme, job.id, blind=False)
    third = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert third is not None and third.id != first.id and ai.llm.calls == calls + 1


async def test_too_few_years_raise_a_knock_out_flag(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    _, application = await setup(app_db, acme, years=2)
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["screening.assess"] = Recorder()
    result = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert result is not None
    assert "Below the minimum of 4 years" in result.knockouts
    assert result.factors["experience"]["notes"] == ["2 years against a minimum of 4"]
