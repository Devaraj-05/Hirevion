"""`hv audit-tail` reads an organisation's newest audit entries, filtered, newest first."""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.db.session import Database
from hirevion_devcli.audit_tail import as_json, audit_tail

pytestmark = pytest.mark.db


async def test_it_lists_an_organisations_newest_entries_and_filters_them(
    app_db: Database, admin_engine: AsyncEngine, make_organization: Any
) -> None:
    org = await make_organization("Acme")
    other = await make_organization("Globex")
    service = AuditService()
    async with app_db.tenant(org) as session:
        for action, resource in (
            ("report.viewed", "iv-1"),
            ("score.modified", "iv-1"),
            ("report.viewed", "iv-2"),
        ):
            await service.append(
                session,
                org,
                AuditEntry(action=action, resource_type="interview", resource_id=resource),
            )
    async with app_db.tenant(other) as session:
        await service.append(session, other, AuditEntry(action="report.viewed", resource_type="x"))
    async with admin_engine.begin() as conn:
        from sqlalchemy import text

        slug = await conn.scalar(text("SELECT slug FROM organizations WHERE id = :i"), {"i": org})
    database = os.environ.get("HV_TEST_DATABASE", "hirevion_test")
    everything = await audit_tail(slug=str(slug), database=database)
    assert [row.action for row in everything] == [
        "report.viewed",
        "score.modified",
        "report.viewed",
    ]
    viewed = await audit_tail(
        slug=str(slug), action="report.viewed", resource="iv-1", database=database
    )
    assert [(row.action, row.resource_id) for row in viewed] == [("report.viewed", "iv-1")]
    assert "report.viewed" in as_json(viewed)
    assert len(await audit_tail(slug=str(slug), limit=1, database=database)) == 1
