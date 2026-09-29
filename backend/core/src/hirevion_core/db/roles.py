"""The database roles the services connect as (ADR-0009).

- `hirevion_app` is what the API and workers use. Row-level security always applies to it.
- `hirevion_relay` only publishes outbox events.

Neither is a superuser, bypasses row-level security or owns a table. Their passwords reach the
server as SCRAM verifiers, so the clear text never appears in a statement or a server log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from hirevion_core.db.rls import identifier
from hirevion_core.settings import APP_ROLE, RELAY_ROLE

SCRAM_ITERATIONS = 4096
# `hv init-env` generates 32 URL-safe characters; SASLprep leaves such passwords unchanged, so
# the verifier computed here matches what libpq and asyncpg send.
PASSWORD_PATTERN = re.compile(r"[A-Za-z0-9_-]{24,}")


def scram_verifier(
    password: str, salt: bytes | None = None, iterations: int = SCRAM_ITERATIONS
) -> str:
    """The SCRAM-SHA-256 verifier PostgreSQL stores for `password` (RFC 5802, RFC 7677)."""
    if not password:
        raise ValueError("the password is empty")
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return f"SCRAM-SHA-256${iterations}:{_b64(salt)}${_b64(stored_key)}:{_b64(server_key)}"


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


async def bootstrap_roles(
    conn: AsyncConnection, database: str, app_password: str, relay_password: str
) -> None:
    """Create the application roles, or reset their attributes and passwords if they exist."""
    database = identifier(database)
    for role, password in ((APP_ROLE, app_password), (RELAY_ROLE, relay_password)):
        if not PASSWORD_PATTERN.fullmatch(password):
            raise ValueError(
                f"the password for {role} must be at least 24 characters of A-Z, a-z, 0-9, _ or -"
            )
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        )
        verb = "ALTER" if exists else "CREATE"
        # exec_driver_sql: the verifier contains ':' and '$', which text() would take for binds.
        await conn.exec_driver_sql(
            f"{verb} ROLE {role} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE "
            f"NOREPLICATION PASSWORD '{scram_verifier(password)}'"
        )
        await conn.exec_driver_sql(f"GRANT CONNECT ON DATABASE {database} TO {role}")
        await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
