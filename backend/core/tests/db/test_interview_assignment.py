"""Assigning, inviting, rescheduling and cancelling interviews, and the scheduler (SP-07a Tasks
3 to 5)."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import aiohttp
import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.access.scope import ResourceScope, resource_scope
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.interviews import assignment, scheduler, templates
from hirevion_core.interviews.assignment import Assignment, InterviewFilters
from hirevion_core.interviews.templates import TemplateFields
from hirevion_core.mail.consumer import MailConsumer
from hirevion_core.mail.sender import SmtpSender
from hirevion_core.mail.settings import MailSettings
from hirevion_core.models import (
    Application,
    CandidateAccount,
    CandidateToken,
    Interview,
    InterviewEvent,
    Invitation,
    OutboxEvent,
)
from hirevion_core.outbox import OutboxRelay

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SETTINGS = IdentitySettings(hibp_enabled=False)
NOW = datetime.now(UTC).replace(microsecond=0)
WINDOW = (NOW + timedelta(days=2), NOW + timedelta(days=3))
EVERYWHERE = ResourceScope(uuid7(), organization_wide=True, team_ids=frozenset())


def actor_for(organization_id: UUID, user_id: UUID) -> Actor:
    return Actor(user_id, organization_id, frozenset(permissions_for(["recruiter"])))


async def assign(
    app_db: Database,
    hiring: Any,
    *,
    application_ids: list[UUID] | None = None,
    invite: bool = True,
    window: tuple[datetime, datetime] = WINDOW,
    **extra: Any,
) -> assignment.AssignResult:
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    async with app_db.tenant(hiring.organization_id) as session:
        return await assignment.assign(
            session,
            actor,
            Assignment(
                application_ids=application_ids or [hiring.application_id],
                template_id=extra.pop("template_id", hiring.template_id),
                starts_at=window[0],
                expires_at=window[1],
                invite=invite,
                **extra,
            ),
            EVERYWHERE,
            settings=SETTINGS,
        )


async def test_an_assigned_interview_has_the_nine_fields_and_a_policy(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    result = await assign(app_db, hiring)
    assert result.skipped == []
    [created] = result.created
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        # PRD §24: id, candidate, job, template version, window, expiry, duration, status, policy.
        assert interview.number == 1
        assert interview.candidate_id == hiring.candidate_id
        assert interview.job_id == hiring.job_id
        assert (interview.template_id, interview.template_version) == (hiring.template_id, 1)
        assert (interview.starts_at, interview.expires_at) == WINDOW
        assert interview.duration_minutes == 45
        assert interview.status == "invited"
        policy = interview.policy
        assert policy["proctoring_level"] == "standard"
        assert "gaze" in policy["checks"] and "camera" in policy["mandatory_checks"]
        assert policy["resume"] == {
            "grace_seconds": 300,
            "max_interruptions": 3,
            "pause_timer": True,
        }
        application = await session.get_one(Application, hiring.application_id)
        assert application.stage == "interview"
        events = (
            await session.scalars(
                select(InterviewEvent.action)
                .where(InterviewEvent.interview_id == interview.id)
                .order_by(InterviewEvent.created_at)
            )
        ).all()
        assert list(events) == ["created", "invited"]
        account = await session.scalar(select(CandidateAccount))
        assert account is not None and account.status == "invited"
        assert interview.candidate_account_id == account.id
        token = await session.scalar(select(CandidateToken))
        assert token is not None and token.purpose == "set_password"
        assert token.expires_at - token.created_at == timedelta(hours=168)
        [sent] = (await session.scalars(select(Invitation))).all()
        assert sent.kind == "invitation"
        assert set(sent.contents) >= {
            "company",
            "job",
            "duration_minutes",
            "window",
            "desktop_instructions",
            "system_requirements",
            "privacy_notice",
            "support",
        }
        topics = (
            await session.scalars(
                select(OutboxEvent.topic).where(
                    OutboxEvent.organization_id == hiring.organization_id
                )
            )
        ).all()
        assert {"interview.created", "mail"} <= set(topics)


async def test_editing_the_template_leaves_the_interview_on_its_pinned_version(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring)).created
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    async with app_db.tenant(hiring.organization_id) as session:
        await templates.update_template(
            session, actor, hiring.template_id, TemplateFields(proctoring_level="strict")
        )
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        assert interview.template_version == 1
        assert interview.policy["proctoring_level"] == "standard"


async def test_bulk_assignment_reports_what_it_skipped(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    ok = await make_hiring(org)
    no_email = await make_hiring(org, template_id=ok.template_id, candidate_email=None)
    rejected = await make_hiring(org, template_id=ok.template_id, stage="rejected")
    taken = await make_hiring(org, template_id=ok.template_id)
    await assign(app_db, taken)
    missing = uuid7()
    result = await assign(
        app_db,
        ok,
        application_ids=[
            ok.application_id,
            no_email.application_id,
            rejected.application_id,
            taken.application_id,
            missing,
        ],
    )
    assert [interview.application_id for interview in result.created] == [ok.application_id]
    assert {(item.application_id, item.code) for item in result.skipped} == {
        (no_email.application_id, "no-email"),
        (rejected.application_id, "stage"),
        (taken.application_id, "already-assigned"),
        (missing, "application-not-found"),
    }


async def test_the_jobs_own_template_is_used_when_none_is_chosen(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    result = await assign(app_db, hiring, template_id=None)
    assert [item.code for item in result.skipped] == ["no-template"]
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE jobs SET interview_template_id = :t WHERE id = :j"),
            {"t": hiring.template_id, "j": hiring.job_id},
        )
    [created] = (await assign(app_db, hiring, template_id=None)).created
    assert created.template_id == hiring.template_id


async def test_windows_are_checked(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    cases = {
        "invalid-window": (NOW + timedelta(days=2), NOW + timedelta(days=1)),
        "window-past": (NOW - timedelta(days=2), NOW - timedelta(days=1)),
        "window-too-short": (NOW + timedelta(hours=1), NOW + timedelta(hours=1, minutes=30)),
        "window-too-long": (NOW, NOW + timedelta(days=31)),
    }
    for code, window in cases.items():
        with pytest.raises(Invalid) as caught:
            await assign(app_db, hiring, window=window)
        assert caught.value.code == code


async def test_scheduling_without_inviting_then_inviting(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring, invite=False)).created
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        assert interview.status == "scheduled"
        assert (await session.get_one(Application, hiring.application_id)).stage == "shortlisted"
        await assignment.invite(session, actor, interview, settings=SETTINGS)
        assert interview.status == "invited"
        # Sending it again resends it, with a fresh link; the old one stops working.
        await assignment.invite(session, actor, interview, settings=SETTINGS)
        tokens = (
            await session.scalars(select(CandidateToken).order_by(CandidateToken.created_at))
        ).all()
        assert [token.used_at is None for token in tokens] == [False, True]
        assert len((await session.scalars(select(Invitation))).all()) == 2


async def test_rescheduling_moves_the_window_and_tells_the_candidate(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring)).created
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    later = (NOW + timedelta(days=5), NOW + timedelta(days=6))
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        await assignment.reschedule(
            session, actor, interview, *later, reason="Clashes with exams", settings=SETTINGS
        )
        assert (interview.starts_at, interview.expires_at) == later
        assert interview.reschedule_count == 1 and interview.status == "invited"
        kinds = (
            await session.scalars(select(Invitation.kind).order_by(Invitation.created_at))
        ).all()
        assert list(kinds) == ["invitation", "reschedule"]


async def test_an_expired_interview_can_be_rescheduled_into_a_new_window(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring)).created
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'expired' WHERE id = :id"), {"id": created.id}
        )
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        await assignment.reschedule(
            session, actor, interview, *WINDOW, reason=None, settings=SETTINGS
        )
        assert interview.status == "invited"


async def test_cancelling_needs_a_reason_and_returns_the_candidate_to_the_shortlist(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring)).created
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        with pytest.raises(Invalid):
            await assignment.cancel(session, actor, interview, reason="  ", settings=SETTINGS)
        await assignment.cancel(session, actor, interview, reason="Role filled", settings=SETTINGS)
        assert interview.status == "cancelled" and interview.ended_at is not None
        assert (await session.get_one(Application, hiring.application_id)).stage == "shortlisted"
        kinds = (await session.scalars(select(Invitation.kind))).all()
        assert "cancellation" in kinds
        with pytest.raises(Conflict):
            await assignment.cancel(session, actor, interview, reason="Again", settings=SETTINGS)
    # The candidate can be given a new interview for the job now.
    assert len((await assign(app_db, hiring)).created) == 1


async def test_reviewers_and_what_the_interviewer_role_sees(
    app_db: Database, make_organization: MakeOrganization, make_hiring, make_user
) -> None:
    org = await make_organization("Acme")
    reviewer = await make_user(org, roles=["interviewer"])
    other = await make_user(org, roles=["interviewer"])
    hiring = await make_hiring(org)
    [created] = (await assign(app_db, hiring, reviewer_ids=[reviewer])).created
    async with app_db.tenant(org) as session:
        scope = await resource_scope(session, reviewer)
        theirs = await session.scalars(
            assignment.interviews_statement(scope, InterviewFilters(), reviewer_only=reviewer)
        )
        assert [row.id for row in theirs] == [created.id]
        nobody = await session.scalars(
            assignment.interviews_statement(scope, InterviewFilters(), reviewer_only=other)
        )
        assert list(nobody) == []
        actor = actor_for(org, hiring.recruiter_id)
        interview = await session.get_one(Interview, created.id)
        assert await assignment.set_reviewers(session, actor, interview, [other]) == [other]
        detail = await assignment.describe(session, interview)
        assert [user.id for user in detail.reviewers] == [other]
        with pytest.raises(Invalid):
            await assignment.set_reviewers(session, actor, interview, [uuid7()])


async def test_the_list_filters_by_tab_and_search(
    app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    first = await make_hiring(org, candidate_name="Meera Iyer")
    second = await make_hiring(org, template_id=first.template_id, candidate_name="Kabir Shah")
    await assign(app_db, first)
    await assign(app_db, second, invite=False)
    async with app_db.tenant(org) as session:

        async def names(filters: InterviewFilters) -> set[int]:
            rows = await session.scalars(assignment.interviews_statement(EVERYWHERE, filters))
            return {row.number for row in rows}

        assert await names(InterviewFilters(status_group="upcoming")) == {1, 2}
        assert await names(InterviewFilters(status_group="live")) == set()
        assert await names(InterviewFilters(query="kabir")) == {2}
        assert await names(InterviewFilters(query="IV-0001")) == {1}
        assert await names(InterviewFilters(status="scheduled")) == {2}


# The scheduler


async def make_due(admin_engine: AsyncEngine, interview_id: UUID, **values: datetime) -> None:
    sets = ", ".join(f"{name} = :{name}" for name in values)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE interviews SET {sets} WHERE id = :id"),  # noqa: S608 (test columns)
            {"id": interview_id, **values},
        )


async def test_the_scheduler_expires_closed_windows(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring)).created
    await make_due(
        admin_engine,
        created.id,
        starts_at=NOW - timedelta(days=3),
        expires_at=NOW - timedelta(minutes=5),
    )
    report = await scheduler.run_due(app_db, SETTINGS, now=NOW)
    assert report.expired >= 1
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        assert interview.status == "expired"


async def test_the_scheduler_reminds_once_before_the_window_opens_and_closes(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring)).created
    await make_due(
        admin_engine,
        created.id,
        invited_at=NOW - timedelta(days=3),
        starts_at=NOW + timedelta(hours=2),
        expires_at=NOW + timedelta(days=3),
    )
    # Two workers at once: only one reminder goes.
    first, second = await asyncio.gather(
        scheduler.run_due(app_db, SETTINGS, now=NOW), scheduler.run_due(app_db, SETTINGS, now=NOW)
    )
    assert first.start_reminders + second.start_reminders == 1
    assert (await scheduler.run_due(app_db, SETTINGS, now=NOW)).start_reminders == 0
    # The window is open, closes within a day and hasn't been started.
    await make_due(
        admin_engine,
        created.id,
        starts_at=NOW - timedelta(days=2),
        expires_at=NOW + timedelta(hours=5),
    )
    assert (await scheduler.run_due(app_db, SETTINGS, now=NOW)).expiry_reminders == 1
    async with app_db.tenant(hiring.organization_id) as session:
        reminders = (
            await session.scalars(select(Invitation).where(Invitation.kind == "reminder"))
        ).all()
        assert sorted(item.contents["reminder"] for item in reminders) == ["closes", "opens"]


# The email itself


async def test_the_invitation_reaches_mailpit_with_all_eight_contents(
    app_db: Database,
    relay_db: Database,
    valkey: Redis,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring,
) -> None:
    org = await make_organization("Acme")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE organizations SET support_email = 'help@acme.example.test' WHERE id = :o"),
            {"o": org},
        )
    email = f"invite-{uuid7().hex[-12:]}@example.test"
    hiring = await make_hiring(org, candidate_email=email)
    await assign(app_db, hiring)
    relay = OutboxRelay(relay_db, valkey)
    while await relay.run_once():
        pass
    consumer = MailConsumer(valkey, SmtpSender(MailSettings(smtp_host="127.0.0.1", smtp_port=1025)))
    # Earlier tests queued mail too; send until the stream is drained.
    while await consumer.run_once():
        pass
    message = await _mailpit_message(email)
    body = " ".join(message["Text"].split())
    for expected in (
        "Acme",
        "Backend Engineer",
        "45 minutes",
        "Window:",
        "/download",
        "System requirements",
        "records your screen, camera, microphone and phone camera",
        "/notices",
        "help@acme.example.test",
        "/invitation/",
    ):
        assert expected in body, expected


async def _mailpit_message(to: str) -> dict[str, Any]:
    api = "http://127.0.0.1:8025/api/v1"
    async with aiohttp.ClientSession() as http:
        for _ in range(50):
            async with http.get(f"{api}/search", params={"query": f'to:"{to}"'}) as response:
                found = (await response.json())["messages"]
            if found:
                async with http.get(f"{api}/message/{found[0]['ID']}") as response:
                    return dict(json.loads(await response.text()))
            await asyncio.sleep(0.1)
    raise AssertionError(f"no email reached {to}")


# Review fixes


async def test_an_expired_interview_cant_be_revived_beside_a_newer_one(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [old] = (await assign(app_db, hiring)).created
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'expired' WHERE id = :id"), {"id": old.id}
        )
    assert len((await assign(app_db, hiring)).created) == 1
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, old.id)
        with pytest.raises(Conflict) as caught:
            await assignment.reschedule(
                session, actor, interview, *WINDOW, reason=None, settings=SETTINGS
            )
        assert caught.value.code == "already-assigned"


async def test_a_never_invited_expired_interview_gets_its_first_invitation(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring, invite=False)).created
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'expired' WHERE id = :id"), {"id": created.id}
        )
    actor = actor_for(hiring.organization_id, hiring.recruiter_id)
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, created.id)
        await assignment.reschedule(
            session, actor, interview, *WINDOW, reason=None, settings=SETTINGS
        )
        kinds = (await session.scalars(select(Invitation.kind))).all()
        assert list(kinds) == ["invitation"]
        assert (await session.get_one(Application, hiring.application_id)).stage == "interview"


async def test_expiry_returns_the_candidate_to_the_shortlist(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    [created] = (await assign(app_db, hiring)).created
    await make_due(
        admin_engine,
        created.id,
        starts_at=NOW - timedelta(days=3),
        expires_at=NOW - timedelta(minutes=5),
    )
    await scheduler.run_due(app_db, SETTINGS, now=NOW)
    async with app_db.tenant(hiring.organization_id) as session:
        assert (await session.get_one(Application, hiring.application_id)).stage == "shortlisted"


async def test_a_removed_email_doesnt_block_cancelling_or_the_scheduler(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    first, second = await make_hiring(org), await make_hiring(org)
    [one] = (await assign(app_db, first)).created
    [two] = (await assign(app_db, second)).created
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE candidates SET email = NULL WHERE id IN (:a, :b)"),
            {"a": first.candidate_id, "b": second.candidate_id},
        )
    actor = actor_for(org, first.recruiter_id)
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, one.id)
        await assignment.cancel(session, actor, interview, reason="Withdrawn", settings=SETTINGS)
        assert interview.status == "cancelled"
    await make_due(
        admin_engine,
        two.id,
        invited_at=NOW - timedelta(days=3),
        starts_at=NOW + timedelta(hours=2),
        expires_at=NOW + timedelta(days=3),
    )
    report = await scheduler.run_due(app_db, SETTINGS, now=NOW)
    assert report.start_reminders == 0
    # Recorded once, so the scheduler doesn't retry it every minute.
    assert (await scheduler.run_due(app_db, SETTINGS, now=NOW)).total == 0
    async with app_db.tenant(org) as session:
        actions = (
            await session.scalars(
                select(InterviewEvent.action).where(InterviewEvent.interview_id == two.id)
            )
        ).all()
        assert "reminder.skipped" in actions
