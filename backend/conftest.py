"""Fixtures shared by every backend package's tests that need the real PostgreSQL and Valkey
(marked `db`).

Locally they use the `hirevion_test` database of `uv run hv up`; CI runs service containers.
The schema is rebuilt from the migrations once per test session.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from io import BytesIO
from typing import Protocol
from uuid import UUID

import pytest
from docx import Document as DocxDocument
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from hirevion_core.db.migrate import migrate
from hirevion_core.db.session import Database, create_database
from hirevion_core.identity.roles import ensure_system_roles
from hirevion_core.ids import uuid7
from hirevion_core.settings import CoreSettings, load_core_settings

TEST_DATABASE = os.environ.get("HV_TEST_DATABASE", "hirevion_test")
# The Valkey logical database the tests own; it is flushed before each test that uses it.
TEST_VALKEY_DB = 15


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        help="also run the `live` tests, which call the real AI vendors (costs a few cents)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # An explicit flag rather than `-m`, which a later `-m` on the command line would replace.
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="calls the real AI vendors; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


async def _reset_schema(settings: CoreSettings, database: str) -> None:
    engine = create_async_engine(settings.database_url("admin", database))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def core_settings() -> CoreSettings:
    return load_core_settings()


@pytest.fixture(scope="session")
def migrated_database(core_settings: CoreSettings) -> str:
    """The test database, reset and migrated once per session."""
    asyncio.run(_reset_schema(core_settings, TEST_DATABASE))
    asyncio.run(migrate(core_settings, TEST_DATABASE))
    return TEST_DATABASE


@pytest.fixture
async def admin_engine(
    core_settings: CoreSettings, migrated_database: str
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(core_settings.database_url("admin", migrated_database))
    yield engine
    await engine.dispose()


@pytest.fixture
def make_organization(admin_engine: AsyncEngine) -> Callable[[str], Awaitable[UUID]]:
    """Creates an organisation, with its system roles, as the admin role (the app role can't)
    and returns its id."""

    async def make(name: str) -> UUID:
        org_id = uuid7()
        async with AsyncSession(admin_engine) as session, session.begin():
            await session.execute(
                text("INSERT INTO organizations (id, name, slug) VALUES (:id, :name, :slug)"),
                {"id": org_id, "name": name, "slug": f"{name.lower()}-{org_id.hex[-12:]}"},
            )
            await ensure_system_roles(session, org_id)
        return org_id

    return make


class MakeUser(Protocol):
    async def __call__(
        self,
        organization_id: UUID,
        *,
        email: str | None = None,
        name: str = "Test User",
        status: str = "active",
        password_hash: str | None = None,
        roles: Sequence[str] = (),
    ) -> UUID: ...


@pytest.fixture
def make_user(admin_engine: AsyncEngine) -> MakeUser:
    """Creates a user (with system roles by key) as the admin role and returns its id."""

    async def make(
        organization_id: UUID,
        *,
        email: str | None = None,
        name: str = "Test User",
        status: str = "active",
        password_hash: str | None = None,
        roles: Sequence[str] = (),
    ) -> UUID:
        user_id = uuid7()
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, organization_id, email, name, status, password_hash) "
                    "VALUES (:id, :org, :email, :name, :status, :hash)"
                ),
                {
                    "id": user_id,
                    "org": organization_id,
                    "email": email or f"user-{user_id.hex[-12:]}@example.test",
                    "name": name,
                    "status": status,
                    "hash": password_hash,
                },
            )
            for key in roles:
                await conn.execute(
                    text(
                        "INSERT INTO user_roles (organization_id, user_id, role_id) "
                        "SELECT :org, :user, id FROM roles WHERE organization_id = :org "
                        "AND key = :key"
                    ),
                    {"org": organization_id, "user": user_id, "key": key},
                )
        return user_id

    return make


@pytest.fixture
async def app_db(core_settings: CoreSettings, migrated_database: str) -> AsyncIterator[Database]:
    db = create_database(core_settings, "app", migrated_database)
    yield db
    await db.dispose()


@pytest.fixture
async def valkey(core_settings: CoreSettings) -> AsyncIterator[Redis]:
    client = Redis.from_url(core_settings.valkey_url(TEST_VALKEY_DB), decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def empty_outbox(admin_engine: AsyncEngine) -> None:
    """Relay tests count events, so they start from an empty outbox."""
    async with admin_engine.begin() as conn:
        await conn.execute(text("DELETE FROM outbox_events"))


@pytest.fixture
async def relay_db(core_settings: CoreSettings, migrated_database: str) -> AsyncIterator[Database]:
    db = create_database(core_settings, "relay", migrated_database)
    yield db
    await db.dispose()


# Tiny, real documents: a one-page PDF (built by hand, with a correct cross-reference table),
# a DOCX (built with python-docx), and the EICAR string.

# The EICAR anti-virus test string: harmless, and every scanner reports it.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def pdf(*lines: str) -> bytes:
    """A one-page PDF showing `lines` in Helvetica."""
    text_ops = "\n".join(
        f"BT /F1 12 Tf 72 {720 - 18 * index} Td ({line}) Tj ET" for index, line in enumerate(lines)
    ).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(text_ops)).encode() + b" >>\nstream\n" + text_ops + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def docx(*paragraphs: str) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Skill"
    table.rows[0].cells[1].text = "Kubernetes"
    out = BytesIO()
    document.save(out)
    return out.getvalue()


@pytest.fixture
def make_pdf() -> Callable[..., bytes]:
    return pdf


@pytest.fixture
def make_docx() -> Callable[..., bytes]:
    return docx


@pytest.fixture
def eicar() -> bytes:
    return EICAR
