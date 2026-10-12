"""The candidate portal's core (SP-07b Task 2; ADR-0022): sessions, the invitation's link, sign-in,
resets, the candidate's interviews and their requests."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.access.scope import ResourceScope
from hirevion_core.candidate_portal import notices, requests
from hirevion_core.candidate_portal.auth import PortalAuthService, PortalLoginOk
from hirevion_core.candidate_portal.interviews import portal_interviews
from hirevion_core.candidate_portal.requests import NewRequest
from hirevion_core.candidate_portal.sessions import resolve_portal_session
from hirevion_core.db.session import Database
from hirevion_core.identity.breach import CompositeChecker, LocalListChecker
from hirevion_core.identity.passwords import PasswordPolicy
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.service import LoginRefused
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.interviews import assignment
from hirevion_core.interviews.assignment import Assignment
from hirevion_core.models import (
    Accommodation,
    CandidateAccount,
    CandidateRequest,
    CandidateWebSession,
    InterviewEvent,
)

pytestmark = pytest.mark.db

SETTINGS = IdentitySettings(hibp_enabled=False)
PASSWORD = "a long candidate passphrase"  # noqa: S105 (a test password)
MakeOrganization = Callable[[str], Awaitable[UUID]]
POLICIES = Path(__file__).resolve().parents[4] / "docs" / "policies"


def _service(app_db: Database, valkey: Redis) -> PortalAuthService:
    return PortalAuthService(
        app_db,
        valkey,
        policy=PasswordPolicy(CompositeChecker(LocalListChecker.from_package()), min_length=12),
        settings=SETTINGS,
    )


async def _invited(
    app_db: Database, make_hiring: Any, org: UUID, *, email: str | None = None
) -> tuple[Any, UUID, str]:
    """A candidate invited to an interview that opened five minutes ago; returns the hiring,
    the interview and the email."""
    address = email or f"cand-{uuid7().hex[-10:]}@example.test"
    hiring = await make_hiring(org, candidate_email=address)
    actor = Actor(hiring.recruiter_id, org, frozenset(permissions_for(["recruiter"])))
    now = datetime.now(UTC)
    async with app_db.tenant(org) as session:
        result = await assignment.assign(
            session,
            actor,
            Assignment(
                application_ids=[hiring.application_id],
                template_id=hiring.template_id,
                starts_at=now - timedelta(minutes=5),
                expires_at=now + timedelta(days=1),
            ),
            ResourceScope(actor.user_id, organization_wide=True, team_ids=frozenset()),
            settings=SETTINGS,
        )
    return hiring, result.created[0].id, address


async def _mailed_token(admin_engine: AsyncEngine, to: str, segment: str) -> str:
    async with admin_engine.connect() as conn:
        payloads = (
            await conn.scalars(
                text(
                    "SELECT payload FROM outbox_events WHERE topic = 'mail' "
                    "AND payload->>'to' = :to ORDER BY created_at DESC"
                ),
                {"to": to},
            )
        ).all()
    for payload in payloads:
        for value in payload["context"].values():
            match = re.search(rf"{segment}([\w-]+)", str(value))
            if match:
                return match.group(1)
    raise AssertionError(f"no {segment} link mailed to {to}")


async def _activated(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_hiring: Any, org: UUID
) -> tuple[Any, UUID, str]:
    hiring, interview_id, email = await _invited(app_db, make_hiring, org)
    token = await _mailed_token(admin_engine, email, "/invitation/")
    assert (
        await _service(app_db, valkey).set_password(token, PASSWORD, ip=None, user_agent=None)
        is None
    )
    return hiring, interview_id, email


async def _account(app_db: Database, org: UUID, candidate_id: UUID) -> CandidateAccount:
    async with app_db.tenant(org) as session:
        return (
            await session.scalars(
                select(CandidateAccount).where(CandidateAccount.candidate_id == candidate_id)
            )
        ).one()


# The invitation's link, sign-in and sessions


async def test_the_invitation_link_sets_the_password_once_and_verifies_the_email(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    hiring, _, email = await _invited(app_db, make_hiring, org)
    token = await _mailed_token(admin_engine, email, "/invitation/")
    service = _service(app_db, valkey)

    assert await service.set_password(token, "too short", ip=None, user_agent=None) == ["too_short"]
    assert await service.set_password(token, PASSWORD, ip=None, user_agent=None) is None
    account = await _account(app_db, org, hiring.candidate_id)
    assert account.status == "active"
    assert account.email_verified_at is not None
    assert await service.set_password(token, PASSWORD, ip=None, user_agent=None) == [
        "invalid_token"
    ]


async def test_sign_in_makes_a_session_that_resolves_and_signs_out(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    service = _service(app_db, valkey)

    result = await service.login(email.upper(), PASSWORD, ip="203.0.113.9", user_agent="Firefox")
    assert isinstance(result, PortalLoginOk)
    now = datetime.now(UTC)
    context = await resolve_portal_session(app_db, result.session_token, settings=SETTINGS, now=now)
    assert context is not None
    assert context.organization_id == org
    view = await service.view(context)
    assert (view.email, view.organization_name) == (email, "Acme")

    # Idle for longer than allowed, or past the absolute limit: gone.
    later = now + SETTINGS.session_idle + timedelta(seconds=1)
    assert (
        await resolve_portal_session(app_db, result.session_token, settings=SETTINGS, now=later)
        is None
    )

    await service.logout(context, ip=None, user_agent=None)
    assert (
        await resolve_portal_session(app_db, result.session_token, settings=SETTINGS, now=now)
        is None
    )
    async with admin_engine.connect() as conn:
        actions = (
            await conn.scalars(
                text("SELECT action FROM audit_logs WHERE organization_id = :o ORDER BY seq"),
                {"o": org},
            )
        ).all()
    assert "candidate.portal.login.succeeded" in actions
    assert "candidate.portal.logout" in actions
    assert "candidate.account.activated" in actions


async def test_a_wrong_password_and_an_unknown_email_get_the_same_refusal_and_lock_out(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    service = _service(app_db, valkey)

    assert await service.login("nobody@example.test", PASSWORD, ip=None, user_agent=None) == (
        LoginRefused(None)
    )
    for _ in range(SETTINGS.lockout_threshold - 1):
        assert await service.login(email, "wrong password!", ip=None, user_agent=None) == (
            LoginRefused(None)
        )
    locked = await service.login(email, "wrong password!", ip=None, user_agent=None)
    assert isinstance(locked, LoginRefused) and locked.retry_after
    # Locked: even the right password is refused, without saying so.
    still = await service.login(email, PASSWORD, ip=None, user_agent=None)
    assert isinstance(still, LoginRefused) and still.retry_after


async def test_an_invited_account_cant_sign_in_before_setting_a_password(
    app_db: Database, valkey: Redis, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await _invited(app_db, make_hiring, org)
    result = await _service(app_db, valkey).login(email, PASSWORD, ip=None, user_agent=None)
    assert result == LoginRefused(None)


async def test_a_reset_ends_portal_sessions_and_desktop_sign_ins(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    service = _service(app_db, valkey)
    signed_in = await service.login(email, PASSWORD, ip=None, user_agent=None)
    assert isinstance(signed_in, PortalLoginOk)

    await service.request_reset(email, ip=None, user_agent=None)
    token = await _mailed_token(admin_engine, email, "/reset-password/")
    new = "another long candidate passphrase"
    assert await service.reset_password(token, new, ip=None, user_agent=None) is None

    now = datetime.now(UTC)
    assert (
        await resolve_portal_session(app_db, signed_in.session_token, settings=SETTINGS, now=now)
        is None
    )
    assert isinstance(await service.login(email, new, ip=None, user_agent=None), PortalLoginOk)
    assert await service.login(email, PASSWORD, ip=None, user_agent=None) == LoginRefused(None)


async def test_forgetting_before_activation_mails_a_fresh_invitation_link(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await _invited(app_db, make_hiring, org)
    first = await _mailed_token(admin_engine, email, "/invitation/")
    await _service(app_db, valkey).request_reset(email, ip=None, user_agent=None)
    fresh = await _mailed_token(admin_engine, email, "/invitation/")
    assert fresh != first
    service = _service(app_db, valkey)
    assert await service.set_password(first, PASSWORD, ip=None, user_agent=None) == [
        "invalid_token"
    ]
    assert await service.set_password(fresh, PASSWORD, ip=None, user_agent=None) is None


async def test_unknown_emails_get_no_reset_mail(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine
) -> None:
    await _service(app_db, valkey).request_reset("ghost@example.test", ip=None, user_agent=None)
    async with admin_engine.connect() as conn:
        mailed = await conn.scalar(
            text("SELECT count(*) FROM outbox_events WHERE payload->>'to' = 'ghost@example.test'")
        )
    assert mailed == 0


# Interviews


async def test_the_candidate_sees_their_invited_interviews_with_windows(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    hiring, interview_id, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    account = await _account(app_db, org, hiring.candidate_id)
    now = datetime.now(UTC)
    async with app_db.tenant(org) as session:
        items = await portal_interviews(session, account, now)
    assert [item.id for item in items] == [interview_id]
    [item] = items
    assert item.job_title == "Backend Engineer"
    assert item.status == "invited" and item.can_take
    assert item.starts_at < now < item.expires_at
    assert item.reference.startswith("IV-")


# Requests


def _actor(hiring: Any, org: UUID) -> Actor:
    return Actor(hiring.recruiter_id, org, frozenset(permissions_for(["recruiter"])))


async def test_a_reschedule_request_is_stored_audited_acknowledged_and_on_the_interview(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    hiring, interview_id, email = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    account = await _account(app_db, org, hiring.candidate_id)
    async with app_db.tenant(org) as session:
        row = await requests.create_request(
            session,
            account,
            NewRequest(
                kind="reschedule",
                message="I'm travelling that week",
                interview_id=interview_id,
                details={"preferred": "Any weekday after the 20th", "ignored": "x"},
            ),
            ip=None,
            user_agent=None,
        )
        request_id = row.id
    async with app_db.tenant(org) as session:
        stored = await session.get_one(CandidateRequest, request_id)
        events = (
            await session.scalars(
                select(InterviewEvent.action).where(InterviewEvent.interview_id == interview_id)
            )
        ).all()
    assert (stored.kind, stored.status) == ("reschedule", "open")
    assert stored.details == {"preferred": "Any weekday after the 20th"}
    assert "reschedule.requested" in events
    async with admin_engine.connect() as conn:
        templates = (
            await conn.scalars(
                text("SELECT payload->>'template' FROM outbox_events WHERE payload->>'to' = :to"),
                {"to": email},
            )
        ).all()
    assert "candidate_request_received" in templates

    scope = ResourceScope(hiring.recruiter_id, organization_wide=True, team_ids=frozenset())
    async with app_db.tenant(org) as session:
        listed = (
            await session.scalars(requests.recruiter_statement(scope, requests.RequestFilters()))
        ).all()
        assert [item.id for item in listed] == [request_id]
        updated = await requests.update_request(
            session, _actor(hiring, org), scope, request_id, status="resolved", response="Moved"
        )
        assert (updated.status, updated.response, updated.handled_by) == (
            "resolved",
            "Moved",
            hiring.recruiter_id,
        )
        with pytest.raises(Conflict):
            await requests.update_request(
                session, _actor(hiring, org), scope, request_id, status="in_progress", response=None
            )


async def test_requests_are_checked_for_their_kind(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    hiring, interview_id, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    other, _, _ = await _invited(app_db, make_hiring, org)
    account = await _account(app_db, org, hiring.candidate_id)
    bad = [
        NewRequest(kind="reschedule", message="please", interview_id=None),
        NewRequest(kind="support", message="  "),
        NewRequest(kind="consent_withdrawal", message="", details={"purposes": ["telepathy"]}),
        NewRequest(kind="accommodation", message="", interview_id=interview_id, details={}),
        NewRequest(kind="nomination", message="", details={"nominee_name": "Ravi"}),
        NewRequest(kind="complaint", message="hello"),
    ]
    for new in bad:
        async with app_db.tenant(org) as session:
            with pytest.raises(Invalid):
                await requests.create_request(session, account, new, ip=None, user_agent=None)
    # Someone else's interview doesn't exist for this candidate.
    async with app_db.tenant(org) as session:
        foreign = await session.scalar(
            text("SELECT id FROM interviews WHERE candidate_id = :c"), {"c": other.candidate_id}
        )
        with pytest.raises(NotFound):
            await requests.create_request(
                session,
                account,
                NewRequest(kind="reschedule", message="please", interview_id=foreign),
                ip=None,
                user_agent=None,
            )


async def test_an_accommodation_request_opens_the_interviews_accommodation(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    hiring, interview_id, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    account = await _account(app_db, org, hiring.candidate_id)
    async with app_db.tenant(org) as session:
        row = await requests.create_request(
            session,
            account,
            NewRequest(
                kind="accommodation",
                message="I use a screen reader",
                interview_id=interview_id,
                details={"kinds": ["assistive_technology", "extended_time"]},
            ),
            ip=None,
            user_agent=None,
        )
        accommodation = (
            await session.scalars(
                select(Accommodation).where(Accommodation.interview_id == interview_id)
            )
        ).one()
    assert accommodation.kinds == ["assistive_technology", "extended_time"]
    assert row.details["accommodation_id"] == str(accommodation.id)


async def test_a_candidate_lists_only_their_own_requests(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    mine, _, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    theirs, _, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    for hiring in (mine, theirs):
        account = await _account(app_db, org, hiring.candidate_id)
        async with app_db.tenant(org) as session:
            await requests.create_request(
                session,
                account,
                NewRequest(kind="data_access", message=""),
                ip=None,
                user_agent=None,
            )
    account = await _account(app_db, org, mine.candidate_id)
    async with app_db.tenant(org) as session:
        own = await requests.list_own(session, account.id)
    assert [item.account_id for item in own] == [account.id]


async def test_a_team_scoped_recruiter_sees_only_requests_of_candidates_they_reach(
    app_db: Database,
    valkey: Redis,
    admin_engine: AsyncEngine,
    make_organization,
    make_hiring,
    make_user,
) -> None:
    org = await make_organization("Acme")
    hiring, _, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    account = await _account(app_db, org, hiring.candidate_id)
    async with app_db.tenant(org) as session:
        row = await requests.create_request(
            session,
            account,
            NewRequest(kind="grievance", message="Unfair"),
            ip=None,
            user_agent=None,
        )
    outsider = await make_user(org, roles=["recruiter"])
    narrow = ResourceScope(outsider, organization_wide=False, team_ids=frozenset())
    async with app_db.tenant(org) as session:
        seen = (
            await session.scalars(requests.recruiter_statement(narrow, requests.RequestFilters()))
        ).all()
        assert seen == []
        with pytest.raises(NotFound):
            await requests.update_request(
                session,
                Actor(outsider, org, frozenset(permissions_for(["recruiter"]))),
                narrow,
                row.id,
                status="in_progress",
                response=None,
            )


async def test_a_request_about_an_interview_follows_the_interviews_scope(
    app_db: Database,
    valkey: Redis,
    admin_engine: AsyncEngine,
    make_organization,
    make_hiring,
    make_user,
) -> None:
    org = await make_organization("Acme")
    hiring, interview_id, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    account = await _account(app_db, org, hiring.candidate_id)
    # This recruiter reaches the candidate (they added them) but not the interview's job.
    outsider = await make_user(org, roles=["recruiter"])
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE candidates SET created_by = :u WHERE id = :c"),
            {"u": outsider, "c": hiring.candidate_id},
        )
    async with app_db.tenant(org) as session:
        about_interview = await requests.create_request(
            session,
            account,
            NewRequest(kind="reschedule", message="please", interview_id=interview_id),
            ip=None,
            user_agent=None,
        )
        general = await requests.create_request(
            session, account, NewRequest(kind="data_access", message=""), ip=None, user_agent=None
        )
    narrow = ResourceScope(outsider, organization_wide=False, team_ids=frozenset())
    async with app_db.tenant(org) as session:
        seen = (
            await session.scalars(requests.recruiter_statement(narrow, requests.RequestFilters()))
        ).all()
    assert [row.id for row in seen] == [general.id]
    assert about_interview.id not in [row.id for row in seen]


async def test_odd_choices_and_unsent_interviews_are_refused(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    hiring, interview_id, _ = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    account = await _account(app_db, org, hiring.candidate_id)
    async with app_db.tenant(org) as session:
        with pytest.raises(Invalid):
            await requests.create_request(
                session,
                account,
                NewRequest(kind="consent_withdrawal", message="", details={"purposes": [{}]}),
                ip=None,
                user_agent=None,
            )
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'scheduled' WHERE id = :i"), {"i": interview_id}
        )
    async with app_db.tenant(org) as session:
        with pytest.raises(NotFound):
            await requests.create_request(
                session,
                account,
                NewRequest(kind="reschedule", message="please", interview_id=interview_id),
                ip=None,
                user_agent=None,
            )


# Notices


def test_the_six_policies_and_ten_disclosures_are_served() -> None:
    policies = notices.load_policies(POLICIES)
    assert [policy.key for policy in policies] == list(notices.POLICY_KEYS)
    assert len(policies) == 6
    privacy = policies[0]
    assert privacy.title == "Privacy policy"
    assert not privacy.body.startswith("# ")
    assert len(notices.DISCLOSURES) == 10
    assert notices.load_policies(POLICIES / "missing") == []


async def test_portal_sessions_are_rows_in_the_tenant(
    app_db: Database, valkey: Redis, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await _activated(app_db, valkey, admin_engine, make_hiring, org)
    result = await _service(app_db, valkey).login(email, PASSWORD, ip=None, user_agent=None)
    assert isinstance(result, PortalLoginOk)
    async with app_db.tenant(org) as session:
        rows = (await session.scalars(select(CandidateWebSession))).all()
    assert len(rows) == 1 and rows[0].token_hash != result.session_token.encode()
