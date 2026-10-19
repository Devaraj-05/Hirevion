"""D1 code review of screening and ranking (SP-05): scoring inputs, the result cache, the
ranking and the recruiter actions. Blind screening, evidence checks and knock-outs that only flag
are kept; these are the gaps the review found around them."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Refused
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
from hirevion_core.models import Application, ApplicationHistory, Candidate, Document, Job
from hirevion_core.screening import config, engine, runner, workflow
from hirevion_core.screening.engine import InputsChanged, screen_application

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]

RESUME = (
    "Priya Nair\npriya@example.test | +91 98765 43210\n\nSkills\nJS, Python\n\n"
    "Experience\nEngineer, Acme Payments (2020 - present)\n- Built a payments gateway\n"
)


def factor(score: int, *quotes: str) -> dict[str, Any]:
    return {"score": score, "evidence": [{"quote": quote} for quote in quotes]}


class Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.reply: dict[str, Any] = {
            "roles": factor(90, "Engineer, Acme Payments"),
            "projects": factor(80, "Built a payments gateway"),
            "domain": factor(70, "payments gateway"),
            "education": factor(100),
            "location": factor(100),
            "strengths": ["Payments experience", "A strong young female engineer"],
            "concerns": [],
            "missing_requirements": [],
        }

    def __call__(self, messages: Sequence[ChatMessage]) -> Any:
        self.sent.append(messages[-1]["content"])
        return self.reply


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def ai(app_db: Database, recorder: Recorder) -> AiServices:
    services = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(services.llm, MockLLM)
    services.llm.scripted["screening.assess"] = recorder
    return services


async def new_application(
    app_db: Database,
    actor: Actor,
    *,
    years: float | None = 6,
    sha: str = "a" * 64,
    job: Job | None = None,
    changes: JobChanges | None = None,
    skills: Sequence[str] = ("JS", "Python"),
    text_: str = RESUME,
) -> tuple[Job, Application]:
    async with app_db.tenant(actor.organization_id) as session:
        job = job or await jobs.create_job(
            session,
            actor,
            changes
            or JobChanges(
                title="Backend Engineer",
                experience_min=Decimal(4),
                skills=[SkillInput("JavaScript"), SkillInput("Python")],
            ),
        )
        document = Document(
            organization_id=actor.organization_id,
            kind="resume",
            job_id=job.id,
            sha256=sha,
            text=text_,
            status="parsed",
            created_by=actor.user_id,
        )
        session.add(document)
        await session.flush()

        def item(value: str) -> dict[str, Any]:
            return {"value": value, "quote": value, "page": 1, "section": None}

        profile = {
            "name": item("Priya Nair"),
            "email": item(f"priya{sha[:4]}@example.test"),
            "skills": [{"name": skill, "years": 4, "quote": skill} for skill in skills],
            "total_experience_years": years,
            "positions": [],
        }
        await profiles.build(
            session, document, ResumeResult(profile, 0, "fake"), flags={}, embedding=None
        )
        application = await session.scalar(
            select(Application).order_by(Application.created_at.desc()).limit(1)
        )
        assert application is not None
        return job, application


async def test_a_fresher_with_zero_years_scores_zero_on_years_not_unknown(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    _, application = await new_application(app_db, acme, years=0)
    result = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert result is not None
    # 0.7 * 0 (no years against a minimum of 4) + 0.3 * 90 (the AI's view of the roles).
    assert result.factors["experience"]["score"] == 27
    assert result.factors["experience"]["notes"] == ["0 years against a minimum of 4"]
    assert result.knockouts == ["Below the minimum of 4 years"]


async def test_a_reset_configuration_does_not_bring_back_results_of_another_one(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    job, application = await new_application(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        await config.save(session, acme, job.id, blind=False)  # version 1 of the job's own
    first = await screen_application(app_db, ai, acme.organization_id, application.id)
    async with app_db.tenant(acme.organization_id) as session:
        await config.reset(session, acme, job.id)
        saved = await config.save(
            session,
            acme,
            job.id,
            weights={**config.DEFAULT_WEIGHTS, "required_skills": 45, "experience": 15},
        )
        assert saved.version == 1  # the number came round again, for another configuration
    assert isinstance(ai.llm, MockLLM)
    calls = ai.llm.calls
    second = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert first is not None and second is not None
    assert second.id != first.id and ai.llm.calls == calls + 1
    # The very same configuration again is the same result.
    again = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert again is not None and again.id == second.id and ai.llm.calls == calls + 1


async def test_saving_what_the_configuration_already_says_is_not_a_new_version(
    app_db: Database, acme: Actor
) -> None:
    job, _ = await new_application(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        first = await config.save(session, acme, job.id, blind=True)
        same = await config.save(session, acme, job.id, blind=True, knockouts={})
        assert (first.version, same.version) == (1, 1)
        nothing = await config.save(session, acme, job.id)
        assert nothing.version == 1
        changed = await config.save(session, acme, job.id, blind=False)
        assert changed.version == 2
    other, _ = await new_application(app_db, acme, sha="b" * 64)
    async with app_db.tenant(acme.organization_id) as session:
        untouched = await config.save(session, acme, other.id)
        assert untouched.inherited is True  # no override row was made for an empty save


async def test_a_built_in_configuration_cannot_be_changed_through_a_copy(
    app_db: Database, acme: Actor
) -> None:
    job, _ = await new_application(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        saved = await config.save(session, acme, job.id, blind=False)
        saved.weights["required_skills"] = 1
        assert (
            config.built_in().weights["required_skills"]
            == config.DEFAULT_WEIGHTS["required_skills"]
        )
        assert config.DEFAULT_WEIGHTS["required_skills"] == 35


async def test_two_applications_with_no_resume_are_each_scored_without_the_ai(
    app_db: Database, acme: Actor, ai: AiServices, recorder: Recorder
) -> None:
    job, _ = await new_application(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        ids = []
        for number in range(2):
            candidate = Candidate(
                organization_id=acme.organization_id, name=f"Empty {number}", profile={}
            )
            session.add(candidate)
            await session.flush()
            application = Application(
                organization_id=acme.organization_id,
                candidate_id=candidate.id,
                job_id=job.id,
                stage="parsed",
            )
            session.add(application)
            await session.flush()
            ids.append(application.id)
    results = [await screen_application(app_db, ai, acme.organization_id, i) for i in ids]
    assert all(result is not None and result.score < 40 for result in results)
    assert results[0] is not None and results[1] is not None and results[0].id != results[1].id
    assert recorder.sent == []  # nothing to read, so nothing was sent
    assert results[0].factors["education"] == {"score": 0, "evidence": [], "supported": False}


async def test_a_resume_replaced_while_the_ai_reads_it_is_not_scored_stale(
    app_db: Database, acme: Actor, ai: AiServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    job, application = await new_application(app_db, acme)
    real = engine.assess

    async def replace_the_resume_then_assess(*args: Any, **kwargs: Any) -> Any:
        async with app_db.tenant(acme.organization_id) as session:
            fresh = Document(
                organization_id=acme.organization_id,
                kind="resume",
                job_id=job.id,
                sha256="c" * 64,
                text="A newer resume",
                status="parsed",
            )
            session.add(fresh)
            await session.flush()
            (await session.get_one(Application, application.id)).document_id = fresh.id
        return await real(*args, **kwargs)

    monkeypatch.setattr(engine, "assess", replace_the_resume_then_assess)
    with pytest.raises(InputsChanged):
        await screen_application(app_db, ai, acme.organization_id, application.id)
    async with app_db.tenant(acme.organization_id) as session:
        assert (await session.get_one(Application, application.id)).screening_result_id is None


async def test_evidence_for_a_skill_follows_the_aliases_the_resume_used(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    _, application = await new_application(app_db, acme)
    result = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert result is not None
    required = result.factors["required_skills"]
    assert required["matched"] == ["JavaScript", "Python"]
    assert required["evidence"] == ["JS", "Python"]  # the resume says JS


async def test_education_and_place_need_quotes_when_the_job_asks_for_them(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    changes = JobChanges(
        title="Backend Engineer",
        qualifications=["M.Tech in Computer Science"],
        location="Pune",
        skills=[SkillInput("Python")],
    )
    _, application = await new_application(app_db, acme, changes=changes)
    result = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert result is not None
    for name in ("education", "location"):
        assert result.factors[name] == {"score": 50, "evidence": [], "supported": False}


async def test_comments_about_who_a_person_is_are_not_kept(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    _, application = await new_application(app_db, acme)
    result = await screen_application(app_db, ai, acme.organization_id, application.id)
    assert result is not None
    assert result.strengths == ["Payments experience"]


async def test_the_blind_resume_has_no_name_even_when_the_parser_found_none(
    app_db: Database, acme: Actor, ai: AiServices, recorder: Recorder
) -> None:
    _, application = await new_application(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        candidate = await session.get_one(Candidate, application.candidate_id)
        candidate.profile = {**candidate.profile, "name": None}
    await screen_application(app_db, ai, acme.organization_id, application.id)
    assert "Priya" not in recorder.sent[0] and "Nair" not in recorder.sent[0]
    assert "Built a payments gateway" in recorder.sent[0]


async def test_equal_scores_are_ranked_in_a_fixed_order(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    job, first = await new_application(app_db, acme, sha="1" * 64)
    ids = [first.id]
    for number in range(2, 5):
        _, application = await new_application(app_db, acme, sha=str(number) * 64, job=job)
        ids.append(application.id)
    async with app_db.tenant(acme.organization_id) as session:
        await session.execute(
            text("UPDATE applications SET created_at = :at WHERE job_id = :job"),
            {"at": datetime(2026, 10, 1, tzinfo=UTC), "job": job.id},
        )
    for application_id in ids:
        await runner.handle_screening_event(
            app_db,
            ai,
            acme.organization_id,
            {"action": "screen", "application_id": str(application_id)},
        )
    async with app_db.tenant(acme.organization_id) as session:
        order = [
            row.id
            for row in (
                await session.scalars(
                    select(Application)
                    .where(Application.job_id == job.id)
                    .order_by(Application.rank)
                )
            ).all()
        ]
        await runner.rerank(session, job.id)
        again = [
            row.id
            for row in (
                await session.scalars(
                    select(Application)
                    .where(Application.job_id == job.id)
                    .order_by(Application.rank)
                )
            ).all()
        ]
    assert order == sorted(ids) == again


async def test_an_application_whose_screening_gave_up_goes_to_a_person_and_does_not_block_ranking(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    job, good = await new_application(app_db, acme, sha="1" * 64)
    _, broken = await new_application(app_db, acme, sha="2" * 64, job=job)
    await runner.handle_screening_event(
        app_db, ai, acme.organization_id, {"action": "screen", "application_id": str(good.id)}
    )
    async with app_db.tenant(acme.organization_id) as session:
        assert (await session.get_one(Application, good.id)).stage == "screened"  # one waits
    await runner.give_up_screening(
        app_db,
        acme.organization_id,
        {"action": "screen", "application_id": str(broken.id), "job_id": str(job.id)},
    )
    async with app_db.tenant(acme.organization_id) as session:
        stored = await session.get_one(Application, broken.id)
        assert stored.stage == "review"
        history = (
            await session.scalars(
                select(ApplicationHistory).where(ApplicationHistory.application_id == broken.id)
            )
        ).all()
        assert "screening_failed" in [h.action for h in history]
        assert (await session.get_one(Application, good.id)).stage == "ranked"


# Recruiter actions


async def test_a_repeated_action_is_a_no_op_that_needs_no_reason_and_a_batch_skips_selected(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    job, first = await new_application(app_db, acme, sha="1" * 64)
    _, second = await new_application(app_db, acme, sha="2" * 64, job=job)
    async with app_db.tenant(acme.organization_id) as session:
        await workflow.act(
            session, acme, job.id, [first.id, second.id], "reject", reason="Not a fit"
        )
        # Sending it again without a reason changes nothing, so it asks for nothing.
        again = await workflow.act(session, acme, job.id, [first.id, second.id], "reject")
        assert [a.stage for a in again] == ["rejected", "rejected"]
        await session.execute(
            text(
                "UPDATE applications SET hiring_status='selected', stage='interviewed' WHERE id=:i"
            ),
            {"i": first.id},
        )
    async with app_db.tenant(acme.organization_id) as session:
        done = await workflow.act(
            session, acme, job.id, [first.id, second.id], "hold", reason="Wait"
        )
        stages = {a.id: a.stage for a in done}
        assert stages == {first.id: "interviewed", second.id: "on_hold"}  # the selected one stays
    async with app_db.tenant(acme.organization_id) as session:
        with pytest.raises(Conflict) as refusal:  # but when nothing could change, say so
            await workflow.act(session, acme, job.id, [first.id], "hold", reason="Wait")
        assert refusal.value.code == "application-selected"


async def test_an_application_with_a_live_interview_is_not_moved_by_a_screening_action(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org, stage="interview")
    await insert_interview(admin_engine, hiring, status="invited")
    recruiter = Actor(hiring.recruiter_id, org, frozenset(permissions_for(["recruiter"])))
    async with app_db.tenant(org) as session:
        with pytest.raises(Conflict) as refusal:
            await workflow.act(
                session, recruiter, hiring.job_id, [hiring.application_id], "reject", reason="No"
            )
        assert refusal.value.code == "interview-active"


async def test_a_decision_after_an_interview_is_reopened_only_by_someone_who_may_decide(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    hiring = scene.hiring
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "UPDATE applications SET stage='rejected', hiring_status='rejected' WHERE id = :id"
            ),
            {"id": hiring.application_id},
        )
    only_manages = Actor(hiring.recruiter_id, org, frozenset({"candidates.manage"}))
    for action in ("shortlist", "hold", "review"):
        async with app_db.tenant(org) as session:
            with pytest.raises(Refused) as refused:
                await workflow.act(
                    session,
                    only_manages,
                    hiring.job_id,
                    [hiring.application_id],
                    action,
                    reason="Hm",
                )
            assert refused.value.code == "decision-forbidden"
    recruiter = Actor(hiring.recruiter_id, org, frozenset(permissions_for(["recruiter"])))
    async with app_db.tenant(org) as session:
        await workflow.act(
            session,
            recruiter,
            hiring.job_id,
            [hiring.application_id],
            "shortlist",
            reason="Second look",
        )
        application = await session.get_one(Application, hiring.application_id)
        assert (application.stage, application.hiring_status) == ("shortlisted", "shortlisted")


async def test_a_rejection_after_an_interview_keeps_the_score_and_rank_in_the_history(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    hiring = scene.hiring
    recruiter = Actor(hiring.recruiter_id, org, frozenset(permissions_for(["recruiter"])))
    async with app_db.tenant(org) as session:
        application = await session.get_one(Application, hiring.application_id)
        application.rank = 3
        await session.execute(
            text("UPDATE applications SET stage='interviewed' WHERE id = :id"),
            {"id": hiring.application_id},
        )
        await workflow.act(
            session, recruiter, hiring.job_id, [hiring.application_id], "reject", reason="Weak"
        )
        last = (
            await session.scalars(
                select(ApplicationHistory)
                .where(ApplicationHistory.application_id == hiring.application_id)
                .order_by(ApplicationHistory.created_at.desc())
            )
        ).first()
        assert last is not None and last.to_stage == "rejected" and last.rank == 3
