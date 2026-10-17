"""The third eye's tables (SP-13, migration 0020): pairings are tenant-scoped, one per interview
is live, revoking is recorded, the phone's lookup works without a tenant; Egress recordings live
beside the desktop's tracks and stay out of the desktop's assembly and continuity listings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import Recording, ThirdEyePairing
from hirevion_core.recordings.segments import ENDED_STATUSES
from hirevion_core.third_eye.pairing import hash_secret, new_secret

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC)


def pairing(org: UUID, interview: UUID, candidate: UUID, **changes: Any) -> ThirdEyePairing:
    fields: dict[str, Any] = {
        "id": uuid7(),
        "organization_id": org,
        "interview_id": interview,
        "candidate_id": candidate,
        "token_hash": hash_secret(new_secret()),
        "expires_at": NOW + timedelta(minutes=2),
    }
    return ThirdEyePairing(**{**fields, **changes})


async def _interview(admin_engine: AsyncEngine, make_hiring: Any, org: UUID) -> tuple[UUID, UUID]:
    hiring = await make_hiring(org)
    interview = await insert_interview(admin_engine, hiring, status="in_progress")
    return interview, hiring.candidate_id


async def test_pairings_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    for org in (acme, globex):
        interview, candidate = await _interview(admin_engine, make_hiring, org)
        async with app_db.tenant(org) as session:
            session.add(pairing(org, interview, candidate))
    async with app_db.tenant(acme) as session:
        rows = (await session.scalars(select(ThirdEyePairing))).all()
    assert [r.organization_id for r in rows] == [acme]


async def test_an_interview_has_one_live_pairing_and_revoking_is_recorded(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview, candidate = await _interview(admin_engine, make_hiring, org)
    first = pairing(org, interview, candidate)
    async with app_db.tenant(org) as session:
        session.add(first)
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            session.add(pairing(org, interview, candidate))
    # A revoked pairing must say when; then another may be issued.
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            row = await session.get_one(ThirdEyePairing, first.id)
            row.status = "revoked"
    async with app_db.tenant(org) as session:
        row = await session.get_one(ThirdEyePairing, first.id)
        row.status, row.revoked_at, row.revoke_reason = "revoked", NOW, "replaced"
        session.add(pairing(org, interview, candidate))
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            session.add(pairing(org, interview, candidate, revoke_reason="lost"))


async def test_the_phone_finds_its_pairing_without_a_tenant(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview, candidate = await _interview(admin_engine, make_hiring, org)
    token, device = new_secret(), new_secret()
    row = pairing(org, interview, candidate, token_hash=hash_secret(token))
    row.device_hash = hash_secret(device)
    async with app_db.tenant(org) as session:
        session.add(row)
    async with app_db.unscoped() as session:
        # The app role reads no pairing without a tenant...
        assert (await session.scalars(select(ThirdEyePairing))).all() == []
        lookup = text("SELECT * FROM auth_third_eye_pairing(:hash)")
        by_token = (await session.execute(lookup, {"hash": hash_secret(token)})).one()
        by_device = (await session.execute(lookup, {"hash": hash_secret(device)})).one()
        nothing = (await session.execute(lookup, {"hash": hash_secret("other")})).all()
    assert (by_token.pairing_id, by_token.organization_id, by_token.matched) == (
        row.id,
        org,
        "token",
    )
    assert by_token.interview_id == interview and by_token.organization_status == "active"
    assert by_device.matched == "device" and nothing == []


def egress_row(org: UUID, interview: UUID, **changes: Any) -> Recording:
    fields: dict[str, Any] = {
        "id": uuid7(),
        "organization_id": org,
        "interview_id": interview,
        "track": "third-eye-1",
        "source": "egress",
        "egress_id": f"EG_{uuid7().hex[-8:]}",
    }
    return Recording(**{**fields, **changes})


async def test_egress_tracks_need_the_egress_source(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview, _ = await _interview(admin_engine, make_hiring, org)
    async with app_db.tenant(org) as session:
        session.add(egress_row(org, interview))
        session.add(egress_row(org, interview, track="conversation-audio-1"))
    for bad in (
        egress_row(org, interview, track="third-eye-2", source="desktop", egress_id=None),
        egress_row(org, interview, track="screen-1"),
        egress_row(org, interview, track="third-eye-0"),
    ):
        with pytest.raises(IntegrityError):
            async with app_db.tenant(org) as session:
                session.add(bad)


async def test_the_desktop_listings_leave_egress_recordings_out(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    live, _ = await _interview(admin_engine, make_hiring, org)
    hiring = await make_hiring(org)
    ended = await insert_interview(admin_engine, hiring, status="completed")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET started_at = :at WHERE id = :id"), {"at": NOW, "id": live}
        )
    async with app_db.tenant(org) as session:
        session.add(egress_row(org, live))
        session.add(egress_row(org, ended, status="recording"))
    async with app_db.unscoped() as session:
        tracks = (
            await session.execute(
                text("SELECT * FROM recording_live_tracks(:now, 10000)"),
                {"now": NOW + timedelta(minutes=1)},
            )
        ).all()
        due = (
            await session.execute(
                text("SELECT * FROM recording_due_assembly(:now, 10000, :ended)"),
                {"now": NOW, "ended": list(ENDED_STATUSES)},
            )
        ).all()
    mine = [row for row in tracks if row.interview_id == live]
    # The interview is still watched (for the desktop's tracks), but not its Egress file.
    assert [row.track for row in mine] == [None]
    assert ended not in {row.interview_id for row in due}
