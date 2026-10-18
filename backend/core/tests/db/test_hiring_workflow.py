"""The hiring workflow (SP-17; PRD §72, ADR-0023): the nine statuses follow the screening stage
and the interview by themselves, a person moves the rest, every change is kept and audited, and a
final decision needs someone authorised to make it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, Refused
from hirevion_core.db.session import Database
from hirevion_core.hiring import workflow
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.models import Application, ApplicationStatusHistory, Interview
from hirevion_core.screening import workflow as screening
from hirevion_core.screening.engine import record_stage

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def actor(org: UUID, user: UUID, *roles: str) -> Actor:
    return Actor(user, org, frozenset(permissions_for(roles)))


async def audited(admin_engine: AsyncEngine, org: UUID, action: str) -> list[dict[str, Any]]:
    async with admin_engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT details, actor_id FROM audit_logs WHERE organization_id = :o "
                "AND action = :a ORDER BY seq"
            ),
            {"o": org, "a": action},
        )
        return [{"details": r.details, "actor": r.actor_id} for r in rows]


async def history(app_db: Database, org: UUID, application: UUID) -> list[ApplicationStatusHistory]:
    async with app_db.tenant(org) as session:
        rows = await session.scalars(
            select(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id == application)
            .order_by(ApplicationStatusHistory.created_at, ApplicationStatusHistory.id)
        )
        return list(rows.all())


async def test_the_status_follows_the_screening_stage_and_the_interview(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org, stage="review")
    async with app_db.tenant(org) as session:
        application = await session.get_one(Application, hiring.application_id)
        assert application.hiring_status == "under_review"
        await record_stage(session, application, "shortlisted", "shortlist", actor_id=None)
        assert application.hiring_status == "shortlisted"
        await record_stage(session, application, "interview", "interview_invited")
        assert application.hiring_status == "interview_invited"
        await record_stage(session, application, "interviewed", "interview_completed")
        assert application.hiring_status == "interview_completed"
    rows = await history(app_db, org, hiring.application_id)
    assert [(r.from_status, r.to_status, r.source) for r in rows] == [
        ("under_review", "shortlisted", "system"),
        ("shortlisted", "interview_invited", "system"),
        ("interview_invited", "interview_completed", "system"),
    ]


async def test_a_person_who_moves_the_stage_is_named_in_the_history(
    app_db: Database,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org, stage="review")
    user = await make_user(org, roles=["recruiter"])
    async with app_db.tenant(org) as session:
        application = await session.get_one(Application, hiring.application_id)
        await record_stage(
            session, application, "on_hold", "hold", actor_id=user, reason="Waiting for budget"
        )
    (row,) = await history(app_db, org, hiring.application_id)
    assert (row.source, row.actor_id, row.reason, row.decision) == (
        "user",
        user,
        "Waiting for budget",
        False,
    )


async def test_an_interview_starting_and_being_abandoned_move_the_status(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org, stage="interview")
    interview_id = await insert_interview(admin_engine, hiring, status="in_progress")
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, interview_id)
        await workflow.sync_interview(session, interview)
        application = await session.get_one(Application, hiring.application_id)
        assert application.hiring_status == "interview_started"
        interview.status = "abandoned"
        await workflow.sync_interview(session, interview)
        assert application.hiring_status == "interview_invited"
    rows = await history(app_db, org, hiring.application_id)
    assert [r.to_status for r in rows] == ["interview_started", "interview_invited"]
    assert {r.interview_id for r in rows} == {interview_id}


async def test_the_system_only_statuses_cannot_be_chosen(
    app_db: Database,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org)
    user = await make_user(org, roles=["recruiter"])
    async with app_db.tenant(org) as session:
        for target in ("interview_invited", "interview_started", "interview_completed"):
            with pytest.raises(Conflict) as error:
                await workflow.change_status(
                    session,
                    actor(org, user, "recruiter"),
                    hiring.application_id,
                    target,
                    reason="because",
                )
            assert error.value.code == "system-status"
        with pytest.raises(Invalid):
            await workflow.change_status(
                session, actor(org, user, "recruiter"), hiring.application_id, "hired", reason="x"
            )


async def test_additional_review_and_hold_need_a_reason_and_are_audited(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org, stage="interviewed")
    user = await make_user(org, roles=["recruiter"])
    me = actor(org, user, "recruiter")
    async with app_db.tenant(org) as session:
        await session.execute(
            text("UPDATE applications SET hiring_status = 'interview_completed' WHERE id = :id"),
            {"id": hiring.application_id},
        )
    async with app_db.tenant(org) as session:
        with pytest.raises(Invalid) as error:
            await workflow.change_status(
                session, me, hiring.application_id, "additional_review", reason="  "
            )
        assert error.value.code == "reason-required"
        row = await workflow.change_status(
            session,
            me,
            hiring.application_id,
            "additional_review",
            reason="Second opinion on system design",
        )
        assert (row.from_status, row.to_status, row.source, row.decision) == (
            "interview_completed",
            "additional_review",
            "user",
            False,
        )
        assert row.actor_id == user
    entries = await audited(admin_engine, org, "hiring.status_changed")
    assert entries[-1]["details"]["to"] == "additional_review"
    assert entries[-1]["details"]["reason"] == "Second opinion on system design"


async def test_only_someone_authorised_makes_the_final_decision(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    manager = await make_user(org, roles=["hiring_manager"])
    recruiter = scene.hiring.recruiter_id
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "UPDATE applications SET stage='interviewed', "
                "hiring_status='interview_completed' WHERE id = :id"
            ),
            {"id": scene.hiring.application_id},
        )
    application = scene.hiring.application_id
    async with app_db.tenant(org) as session:
        # A hiring manager gives input, never the decision.
        with pytest.raises(Refused) as refused:
            await workflow.change_status(
                session,
                actor(org, manager, "hiring_manager"),
                application,
                "selected",
                reason="Great fit",
            )
        assert refused.value.code == "decision-forbidden"
        with pytest.raises(Invalid):  # a decision says why
            await workflow.change_status(
                session, actor(org, recruiter, "recruiter"), application, "selected", reason=""
            )
        row = await workflow.change_status(
            session,
            actor(org, recruiter, "recruiter"),
            application,
            "selected",
            reason="Strong across the board",
        )
        assert row.decision is True and row.interview_id == scene.interview_id
    entries = await audited(admin_engine, org, "hiring.decided")
    assert entries[-1]["details"]["decision"] == "selected"
    # The system no longer moves a selected candidate, whatever the stage does.
    async with app_db.tenant(org) as session:
        current = await session.get_one(Application, application)
        await record_stage(session, current, "interview", "interview_invited")
        assert current.hiring_status == "selected"


async def test_selecting_needs_a_finished_interview(
    app_db: Database,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org)
    async with app_db.tenant(org) as session:
        with pytest.raises(Conflict) as error:
            await workflow.change_status(
                session,
                actor(org, hiring.recruiter_id, "recruiter"),
                hiring.application_id,
                "selected",
                reason="No interview yet",
            )
        assert error.value.code == "no-interview"


async def test_rejecting_before_any_interview_is_the_screening_action(
    app_db: Database,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org)
    async with app_db.tenant(org) as session:
        row = await workflow.change_status(
            session,
            actor(org, hiring.recruiter_id, "recruiter"),
            hiring.application_id,
            "rejected",
            reason="Does not meet the must-haves",
        )
        application = await session.get_one(Application, hiring.application_id)
        assert application.stage == "rejected" and application.hiring_status == "rejected"
        assert row.decision is False and row.source == "user"


async def test_a_decision_can_be_reversed_only_by_someone_who_may_decide(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    application = scene.hiring.application_id
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "UPDATE applications SET stage='interviewed', hiring_status='selected' "
                "WHERE id = :id"
            ),
            {"id": application},
        )
    peer = await make_user(org, roles=["interviewer"])
    async with app_db.tenant(org) as session:
        with pytest.raises(Refused):
            await workflow.change_status(
                session, actor(org, peer, "interviewer"), application, "on_hold", reason="Hmm"
            )
        row = await workflow.change_status(
            session,
            actor(org, scene.hiring.recruiter_id, "recruiter"),
            application,
            "on_hold",
            reason="The offer was withdrawn",
        )
        assert row.from_status == "selected" and row.decision is True


async def test_assigning_someone_does_not_rewrite_a_status_that_is_further_along(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    hiring = scene.hiring
    manager = await make_user(org, roles=["hiring_manager"])
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "UPDATE applications SET stage='interviewed', hiring_status='additional_review' "
                "WHERE id = :id"
            ),
            {"id": hiring.application_id},
        )
    async with app_db.tenant(org) as session:
        await screening.act(
            session,
            actor(org, hiring.recruiter_id, "recruiter"),
            hiring.job_id,
            [hiring.application_id],
            "assign_hiring_manager",
            user_id=manager,
        )
        application = await session.get_one(Application, hiring.application_id)
        assert application.hiring_manager_id == manager
        assert application.hiring_status == "additional_review"
    assert await history(app_db, org, hiring.application_id) == []


async def test_a_status_another_request_changed_is_not_judged_from_a_stale_copy(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    application_id = scene.hiring.application_id
    manager = await make_user(org, roles=["hiring_manager"])
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "UPDATE applications SET stage='interviewed', "
                "hiring_status='interview_completed' WHERE id = :id"
            ),
            {"id": application_id},
        )
    async with app_db.tenant(org) as session:
        await session.get_one(Application, application_id)  # the route's copy: not yet decided
        await session.execute(  # a decision lands meanwhile, outside this session's view
            update(Application)
            .where(Application.id == application_id)
            .values(hiring_status="selected")
            .execution_options(synchronize_session=False)
        )
        with pytest.raises(Refused) as refused:
            await workflow.change_status(
                session,
                actor(org, manager, "hiring_manager"),
                application_id,
                "on_hold",
                reason="Hmm",
            )
        assert refused.value.code == "decision-forbidden"


async def test_the_screening_actions_cannot_decide_or_reopen_a_decision(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    hiring = scene.hiring
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "UPDATE applications SET stage='interviewed', "
                "hiring_status='interview_completed' WHERE id = :id"
            ),
            {"id": hiring.application_id},
        )
    only_manages = Actor(hiring.recruiter_id, org, frozenset({"candidates.manage"}))
    async with app_db.tenant(org) as session:
        with pytest.raises(Refused) as refused:  # a rejection after an interview is a decision
            await screening.act(
                session, only_manages, hiring.job_id, [hiring.application_id], "reject", reason="No"
            )
        assert refused.value.code == "decision-forbidden"
    async with app_db.tenant(org) as session:
        await screening.act(
            session,
            actor(org, hiring.recruiter_id, "recruiter"),
            hiring.job_id,
            [hiring.application_id],
            "reject",
            reason="Weak answers on PostgreSQL",
        )
        application = await session.get_one(Application, hiring.application_id)
        assert (application.stage, application.hiring_status) == ("rejected", "rejected")
    last = (await history(app_db, org, hiring.application_id))[-1]
    assert last.decision is True and last.reason == "Weak answers on PostgreSQL"
    assert (await audited(admin_engine, org, "hiring.decided"))[-1]["details"]["to"] == "rejected"
    # A selected application is only moved by changing its hiring status.
    async with app_db.tenant(org) as session:
        await session.execute(
            text("UPDATE applications SET hiring_status='selected' WHERE id = :id"),
            {"id": hiring.application_id},
        )
    async with app_db.tenant(org) as session:
        with pytest.raises(Conflict) as conflict:
            await screening.act(
                session,
                actor(org, hiring.recruiter_id, "recruiter"),
                hiring.job_id,
                [hiring.application_id],
                "shortlist",
            )
        assert conflict.value.code == "application-selected"


async def test_the_interview_does_not_undo_what_a_person_decided(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org, stage="interview")
    interview_id = await insert_interview(admin_engine, hiring, status="in_progress")
    for held in ("rejected", "on_hold", "additional_review"):
        async with app_db.tenant(org) as session:
            await session.execute(
                text("UPDATE applications SET hiring_status = :held WHERE id = :id"),
                {"held": held, "id": hiring.application_id},
            )
        async with app_db.tenant(org) as session:
            interview = await session.get_one(Interview, interview_id)
            application = await session.get_one(Application, hiring.application_id)
            await workflow.sync_interview(session, interview)  # the candidate starts anyway
            assert application.hiring_status == held
            await record_stage(session, application, "interviewed", "interview_completed")
            assert application.hiring_status == held  # nor does the stage the system sets
            application.stage = "interview"
    # A person's own stage move still goes through.
    async with app_db.tenant(org) as session:
        application = await session.get_one(Application, hiring.application_id)
        await record_stage(
            session, application, "shortlisted", "shortlist", actor_id=hiring.recruiter_id
        )
        assert application.hiring_status == "shortlisted"


def test_the_menu_never_offers_a_move_the_server_would_refuse() -> None:
    # Moving out of a decision is reopening it.
    assert workflow.allowed_targets("rejected", can_decide=False, has_interview=True) == []
    assert "under_review" in workflow.allowed_targets(
        "rejected", can_decide=True, has_interview=True
    )
    # A rejection before any interview is the plain screening action.
    assert workflow.allowed_targets("rejected", can_decide=False, has_interview=False)


def test_what_a_person_can_choose_next() -> None:
    plain = workflow.allowed_targets("interview_completed", can_decide=False, has_interview=True)
    assert plain == ["under_review", "shortlisted", "additional_review", "on_hold"]
    full = workflow.allowed_targets("interview_completed", can_decide=True, has_interview=True)
    assert full == [
        "under_review",
        "shortlisted",
        "additional_review",
        "selected",
        "rejected",
        "on_hold",
    ]
    nobody_interviewed = workflow.allowed_targets(
        "shortlisted", can_decide=True, has_interview=False
    )
    assert "selected" not in nobody_interviewed and "rejected" in nobody_interviewed
    assert workflow.allowed_targets("selected", can_decide=False, has_interview=True) == []
