"""The desktop's sign-in contract over HTTP (SP-07c Tasks 4 to 6, 8): `candidate-auth.md` end to
end, with a simulated desktop holding its own P-256 key.

Exit criteria: a replayed proof, a stolen token without the key, and an outdated app are each
refused.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.scope import ResourceScope
from hirevion_core.db.session import Database
from hirevion_core.identity.passwords import hash_password
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.interviews import assignment
from hirevion_core.interviews.assignment import Assignment

pytestmark = pytest.mark.db

BASE = "http://api.hirevion.localhost"
PASSWORD = "a long candidate passphrase"  # noqa: S105 (a test password)
APP = {"version": "1.4.0", "channel": "stable", "os": "Windows 11 26200", "arch": "x64"}
SETTINGS = IdentitySettings(hibp_enabled=False)
MakeOrganization = Callable[[str], Awaitable[UUID]]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Desktop:
    """What the desktop app does: one device key, a fresh proof per request."""

    def __init__(self, client: AsyncClient) -> None:
        self.client = client
        self.key = ec.generate_private_key(ec.SECP256R1())
        numbers = self.key.public_key().public_numbers()
        self.jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64(numbers.x.to_bytes(32, "big")),
            "y": _b64(numbers.y.to_bytes(32, "big")),
        }
        self.access: str | None = None
        self.refresh: str | None = None
        self.last_proof: str | None = None

    def proof(self, method: str, path: str, token: str | None = None) -> str:
        claims: dict[str, Any] = {
            "jti": str(uuid.uuid4()),
            "htm": method,
            "htu": f"{BASE}/api/v1{path}",
            "iat": int(time.time()),
        }
        if token is not None:
            import hashlib

            claims["ath"] = _b64(hashlib.sha256(token.encode()).digest())
        self.last_proof = jwt.encode(
            claims, self.key, algorithm="ES256", headers={"typ": "dpop+jwt", "jwk": self.jwk}
        )
        return self.last_proof

    async def call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        token: str | None = None,
        proof: str | None = None,
    ) -> Response:
        headers = {
            "DPoP": proof or self.proof(method, path, token),
            "User-Agent": "HirevionInterview/1.4.0 (Windows 26200; x64)",
        }
        if token is not None:
            headers["Authorization"] = f"DPoP {token}"
        return await self.client.request(method, f"/api/v1{path}", json=json_body, headers=headers)

    async def login(self, email: str, password: str = PASSWORD, **app: str) -> Response:
        response = await self.call(
            "POST",
            "/candidate-auth/login",
            json_body={
                "email": email,
                "password": password,
                "app": {**APP, **app},
                "device": {"name": "ASHA-LAPTOP"},
            },
        )
        if response.status_code == 200 and response.json()["status"] == "ok":
            self.access = response.json()["access_token"]
            self.refresh = response.json()["refresh_token"]
        return response


@pytest.fixture
def client(api: FastAPI, client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    return client_for(api)


async def invited_candidate(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_hiring: Any,
    organization_id: UUID,
    *,
    email: str | None = None,
    starts_at: datetime | None = None,
    new_device_otp: bool = False,
) -> tuple[Any, UUID, str]:
    """A candidate invited to an interview, with an active account and `PASSWORD`."""
    address = email or f"cand-{uuid7().hex[-10:]}@example.test"
    hiring = await make_hiring(organization_id, candidate_email=address)
    actor = Actor(hiring.recruiter_id, organization_id, frozenset(permissions_for(["recruiter"])))
    now = datetime.now(UTC)
    opens = starts_at or now - timedelta(minutes=5)
    async with app_db.tenant(organization_id) as session:
        result = await assignment.assign(
            session,
            actor,
            Assignment(
                application_ids=[hiring.application_id],
                template_id=hiring.template_id,
                starts_at=opens,
                expires_at=max(opens, now) + timedelta(days=1),
            ),
            ResourceScope(actor.user_id, organization_wide=True, team_ids=frozenset()),
            settings=SETTINGS,
        )
    [interview] = result.created
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE candidate_accounts SET status = 'active', password_hash = :hash "
                "WHERE candidate_id = :candidate"
            ),
            {"hash": hash_password(PASSWORD), "candidate": hiring.candidate_id},
        )
        await conn.execute(
            text(
                "INSERT INTO organization_settings (organization_id, candidate_access) "
                "VALUES (:org, :settings) ON CONFLICT (organization_id) "
                "DO UPDATE SET candidate_access = excluded.candidate_access"
            ),
            {"org": organization_id, "settings": json.dumps({"new_device_otp": new_device_otp})},
        )
    return hiring, interview.id, address


async def latest_code(admin_engine: AsyncEngine, to: str) -> str:
    async with admin_engine.connect() as conn:
        payload = await conn.scalar(
            text(
                "SELECT payload FROM outbox_events WHERE topic = 'mail' "
                "AND payload->>'template' = 'candidate_code' AND payload->>'to' = :to "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"to": to},
        )
    return str(payload["context"]["code"])


async def test_sign_in_me_session_token_and_sign_out(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, interview_id, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    desktop = Desktop(client)
    response = await desktop.login(email)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok" and body["token_type"] == "DPoP"  # noqa: S105
    assert body["expires_in"] == 600 and body["refresh_expires_in"] == 28800
    assert body["refresh_token"].startswith("rt_")
    assert body["organization"]["name"] == "Acme"
    assert [item["id"] for item in body["interviews"]] == [str(interview_id)]
    assert body["interviews"][0]["status"] == "invited"
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["aud"] == "hirevion-desktop" and claims["scope"] == "candidate"
    assert set(claims["cnf"]) == {"jkt"}

    me = await desktop.call("GET", "/candidate-auth/me", token=desktop.access)
    assert me.status_code == 200, me.text
    assert me.json()["interviews"][0]["id"] == str(interview_id)

    path = f"/candidate-auth/interviews/{interview_id}/session-token"
    session = await desktop.call("POST", path, token=desktop.access)
    assert session.status_code == 200, session.text
    session_claims = jwt.decode(
        session.json()["session_token"], options={"verify_signature": False}
    )
    assert session_claims["scope"] == "interview"
    assert session_claims["interview_id"] == str(interview_id)

    out = await desktop.call("POST", "/candidate-auth/logout", token=desktop.access)
    assert out.status_code == 204
    after = await desktop.call("GET", "/candidate-auth/me", token=desktop.access)
    assert after.status_code == 401 and after.json()["code"] == "token-invalid"
    refreshed = await desktop.call(
        "POST", "/candidate-auth/refresh", json_body={"refresh_token": desktop.refresh}
    )
    assert refreshed.status_code == 401 and refreshed.json()["code"] == "refresh-invalid"


async def test_a_replayed_proof_is_refused(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    desktop = Desktop(client)
    assert (await desktop.login(email)).status_code == 200
    proof = desktop.proof("GET", "/candidate-auth/me", desktop.access)
    first = await desktop.call("GET", "/candidate-auth/me", token=desktop.access, proof=proof)
    assert first.status_code == 200
    again = await desktop.call("GET", "/candidate-auth/me", token=desktop.access, proof=proof)
    assert again.status_code == 401 and again.json()["code"] == "dpop-invalid"
    assert "DPoP" in again.headers["www-authenticate"]


async def test_a_stolen_token_without_the_device_key_is_refused(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, interview_id, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    victim = Desktop(client)
    assert (await victim.login(email)).status_code == 200
    thief = Desktop(client)
    stolen = await thief.call("GET", "/candidate-auth/me", token=victim.access)
    assert stolen.status_code == 401 and stolen.json()["code"] == "dpop-invalid"
    no_proof = await client.get(
        "/api/v1/candidate-auth/me", headers={"Authorization": f"DPoP {victim.access}"}
    )
    assert no_proof.status_code == 401 and no_proof.json()["code"] == "dpop-invalid"
    refresh = await thief.call(
        "POST", "/candidate-auth/refresh", json_body={"refresh_token": victim.refresh}
    )
    assert refresh.status_code == 401 and refresh.json()["code"] == "dpop-invalid"
    # A session token's scope can't be used as an access token, nor for another interview.
    path = f"/candidate-auth/interviews/{interview_id}/session-token"
    session = (await victim.call("POST", path, token=victim.access)).json()["session_token"]
    wrong_scope = await victim.call("GET", "/candidate-auth/me", token=session)
    assert wrong_scope.status_code == 401 and wrong_scope.json()["code"] == "token-invalid"


async def test_an_outdated_app_is_refused_at_sign_in_and_refresh(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    desktop = Desktop(client)
    assert (await desktop.login(email)).status_code == 200
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE desktop_channels SET minimum_version = '1.5.0', "
                "download_url = 'https://downloads.hirevion.localhost/AI-Interview.exe' "
                "WHERE channel = 'stable'"
            )
        )
    try:
        response = await Desktop(client).login(email)
        assert response.status_code == 426
        assert response.json()["code"] == "app-update-required"
        assert response.json()["minimum_version"] == "1.5.0"
        assert response.json()["download_url"].endswith("AI-Interview.exe")
        refreshed = await desktop.call(
            "POST", "/candidate-auth/refresh", json_body={"refresh_token": desktop.refresh}
        )
        assert refreshed.status_code == 426
        newer = await Desktop(client).login(email, version="1.5.0")
        assert newer.status_code == 200
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(text("UPDATE desktop_channels SET minimum_version = '0.0.0'"))


async def test_wrong_passwords_and_unknown_emails_look_the_same_then_lock(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    desktop = Desktop(client)
    unknown = await desktop.login("nobody@example.test")
    wrong = await desktop.login(email, "not the right passphrase")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "invalid-credentials"
    for _ in range(3):
        await desktop.login(email, "still not the passphrase")
    locked = await desktop.login(email, "and still wrong again")
    assert locked.status_code == 423 and locked.json()["code"] == "account-locked"
    assert int(locked.headers["retry-after"]) > 0
    # Even the right password waits out the lock.
    assert (await desktop.login(email)).status_code == 423


async def test_the_interview_checks_in_order(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    hiring, interview_id, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    desktop = Desktop(client)

    async def set_sql(sql: str, **values: Any) -> None:
        async with admin_engine.begin() as conn:
            await conn.execute(text(sql), values)

    await set_sql(
        "UPDATE interviews SET expires_at = now() - interval '1 minute', "
        "starts_at = now() - interval '2 days' WHERE id = :id",
        id=interview_id,
    )
    expired = await desktop.login(email)
    assert expired.status_code == 403 and expired.json()["code"] == "interview-expired"
    assert "expired_at" in expired.json()
    await set_sql("UPDATE interviews SET status = 'completed' WHERE id = :id", id=interview_id)
    done = await desktop.login(email)
    assert done.status_code == 403 and done.json()["code"] == "interview-not-available"
    assert done.json()["interview_status"] == "completed"
    await set_sql("UPDATE jobs SET status = 'closed' WHERE id = :id", id=hiring.job_id)
    closed = await desktop.login(email)
    assert closed.status_code == 403 and closed.json()["code"] == "job-closed"
    await set_sql("UPDATE interviews SET status = 'cancelled' WHERE id = :id", id=interview_id)
    none = await desktop.login(email)
    assert none.status_code == 403 and none.json()["code"] == "no-interview"


async def test_a_new_device_needs_the_emailed_code(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(
        app_db, admin_engine, make_hiring, org, new_device_otp=True
    )
    desktop = Desktop(client)
    challenge = await desktop.login(email)
    assert challenge.status_code == 200, challenge.text
    body = challenge.json()
    assert body["status"] == "otp_required" and body["expires_in"] == 600
    assert body["sent_to"].startswith(email[0]) and "***@example.test" in body["sent_to"]
    code = await latest_code(admin_engine, email)
    wrong_code = f"{(int(code) + 1) % 1_000_000:06d}"

    verify = "/candidate-auth/otp/verify"
    wrong = await desktop.call(
        "POST", verify, json_body={"challenge_id": body["challenge_id"], "code": wrong_code}
    )
    assert wrong.status_code == 400 and wrong.json()["code"] == "otp-invalid"
    assert wrong.json()["attempts_left"] == 4
    # Another device can't use this device's challenge.
    other = Desktop(client)
    stolen = await other.call(
        "POST", verify, json_body={"challenge_id": body["challenge_id"], "code": code}
    )
    assert stolen.status_code == 401
    right = await desktop.call(
        "POST", verify, json_body={"challenge_id": body["challenge_id"], "code": code}
    )
    assert right.status_code == 200, right.text
    assert right.json()["status"] == "ok"
    used = await desktop.call(
        "POST", verify, json_body={"challenge_id": body["challenge_id"], "code": code}
    )
    assert used.status_code == 410 and used.json()["code"] == "otp-expired"
    # The device is known now: the next sign-in needs no code.
    again = await desktop.login(email)
    assert again.status_code == 200 and again.json()["status"] == "ok"
    resend = await desktop.call(
        "POST", "/candidate-auth/otp/resend", json_body={"challenge_id": body["challenge_id"]}
    )
    assert resend.status_code == 410


async def test_too_many_wrong_codes_kill_the_challenge(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(
        app_db, admin_engine, make_hiring, org, new_device_otp=True
    )
    desktop = Desktop(client)
    challenge = (await desktop.login(email)).json()["challenge_id"]
    code = await latest_code(admin_engine, email)
    wrong_code = f"{(int(code) + 1) % 1_000_000:06d}"
    statuses = []
    for _ in range(5):
        response = await desktop.call(
            "POST",
            "/candidate-auth/otp/verify",
            json_body={"challenge_id": challenge, "code": wrong_code},
        )
        statuses.append(response.status_code)
    assert statuses == [400, 400, 400, 400, 429]
    right = await desktop.call(
        "POST", "/candidate-auth/otp/verify", json_body={"challenge_id": challenge, "code": code}
    )
    assert right.status_code == 429 and right.json()["code"] == "otp-attempts-exceeded"
    soon = await desktop.call(
        "POST", "/candidate-auth/otp/resend", json_body={"challenge_id": challenge}
    )
    # A dead challenge can't be revived by asking for another code.
    assert soon.status_code == 429 and soon.json()["code"] == "otp-attempts-exceeded"


async def test_refresh_rotates_and_a_reused_token_revokes_the_family(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    desktop = Desktop(client)
    assert (await desktop.login(email)).status_code == 200
    first = desktop.refresh
    rotated = await desktop.call(
        "POST", "/candidate-auth/refresh", json_body={"refresh_token": first}
    )
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()["refresh_token"]
    assert second != first and rotated.json()["refresh_expires_in"] <= 28800
    access = rotated.json()["access_token"]
    assert (await desktop.call("GET", "/candidate-auth/me", token=access)).status_code == 200
    reused = await desktop.call(
        "POST", "/candidate-auth/refresh", json_body={"refresh_token": first}
    )
    assert reused.status_code == 401 and reused.json()["code"] == "refresh-reused"
    # The whole family is dead: the newest refresh token and the access token too.
    dead = await desktop.call(
        "POST", "/candidate-auth/refresh", json_body={"refresh_token": second}
    )
    assert dead.status_code == 401
    assert (await desktop.call("GET", "/candidate-auth/me", token=access)).status_code == 401


async def test_a_session_token_waits_for_the_window(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, interview_id, email = await invited_candidate(
        app_db,
        admin_engine,
        make_hiring,
        org,
        starts_at=datetime.now(UTC) + timedelta(hours=3),
    )
    desktop = Desktop(client)
    assert (await desktop.login(email)).status_code == 200
    path = f"/candidate-auth/interviews/{interview_id}/session-token"
    early = await desktop.call("POST", path, token=desktop.access)
    assert early.status_code == 409 and early.json()["code"] == "interview-not-open"
    assert "starts_at" in early.json()
    other = await desktop.call(
        "POST", f"/candidate-auth/interviews/{uuid7()}/session-token", token=desktop.access
    )
    assert other.status_code == 404


async def test_releases_check_rollout_and_manifest(
    client: AsyncClient, admin_engine: AsyncEngine, signed_in, make_user
) -> None:
    from hirevion_core.identity import PLATFORM_ORGANIZATION_ID

    admin = await signed_in(
        PLATFORM_ORGANIZATION_ID, await make_user(PLATFORM_ORGANIZATION_ID, roles=["super_admin"])
    )
    version = f"9.{uuid7().int % 1000}.0"
    created = await admin.post(
        "/api/v1/platform/desktop-releases",
        json={
            "version": version,
            "channel": "beta",
            "arch": "x64",
            "url": f"https://downloads.hirevion.localhost/AI-Interview_{version}_x64-setup.nsis.zip",
            "signature": "untrusted comment: minisign\nRWS...",
            "notes": "Faster start-up",
            "rollout_percent": 0,
        },
    )
    assert created.status_code == 201, created.text
    release = created.json()
    assert release["status"] == "draft"
    manifest = "/api/v1/desktop/update-manifest/windows/x86_64/1.0.0?channel=beta"
    assert (await client.get(manifest)).status_code == 204
    published = await admin.patch(
        f"/api/v1/platform/desktop-releases/{release['id']}",
        json={"status": "published", "rollout_percent": 100},
    )
    assert published.status_code == 200 and published.json()["published_at"]
    offered = await client.get(manifest)
    assert offered.status_code == 200
    assert offered.json()["version"] == version
    assert offered.json()["platforms"]["windows-x86_64"]["url"].endswith("nsis.zip")
    # Never a downgrade: a newer app gets nothing.
    newer = await client.get("/api/v1/desktop/update-manifest/windows/x86_64/99.0.0?channel=beta")
    assert newer.status_code == 204
    check = await client.get(
        "/api/v1/desktop/releases/check", params={"version": "1.0.0", "channel": "beta"}
    )
    assert check.status_code == 200
    assert check.json()["status"] == "update-available"
    assert check.json()["latest"]["version"] == version
    bad = await client.get("/api/v1/desktop/releases/check", params={"version": "one"})
    assert bad.status_code == 422
    withdrawn = await admin.patch(
        f"/api/v1/platform/desktop-releases/{release['id']}", json={"status": "withdrawn"}
    )
    assert withdrawn.status_code == 200
    assert (await client.get(manifest)).status_code == 204
    registry = await admin.get("/api/v1/platform/desktop-releases")
    assert {item["channel"] for item in registry.json()["channels"]} == {"stable", "beta"}


async def test_the_new_device_setting_is_the_organisations(
    signed_in, make_organization: MakeOrganization, make_user
) -> None:
    org = await make_organization("Acme")
    admin = await signed_in(org, await make_user(org, roles=["org_admin"]))
    current = await admin.get("/api/v1/organization/candidate-access")
    assert current.status_code == 200 and current.json() == {"new_device_otp": True}
    off = await admin.put("/api/v1/organization/candidate-access", json={"new_device_otp": False})
    assert off.status_code == 200 and off.json() == {"new_device_otp": False}


# Review fixes


async def test_resending_doesnt_revive_a_dead_challenge_or_work_for_another_key(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(
        app_db, admin_engine, make_hiring, org, new_device_otp=True
    )
    desktop = Desktop(client)
    challenge = (await desktop.login(email)).json()["challenge_id"]
    other = Desktop(client)
    foreign = await other.call(
        "POST", "/candidate-auth/otp/resend", json_body={"challenge_id": challenge}
    )
    assert foreign.status_code == 401 and foreign.json()["code"] == "dpop-invalid"
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE candidate_otps SET attempts = 5, "
                "last_sent_at = now() - interval '5 minutes' WHERE id = :id"
            ),
            {"id": challenge},
        )
    dead = await desktop.call(
        "POST", "/candidate-auth/otp/resend", json_body={"challenge_id": challenge}
    )
    assert dead.status_code == 429 and dead.json()["code"] == "otp-attempts-exceeded"


async def test_revoking_a_device_stops_its_tokens_at_once(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(app_db, admin_engine, make_hiring, org)
    desktop = Desktop(client)
    assert (await desktop.login(email)).status_code == 200
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE candidate_devices SET revoked_at = now()"))
    refused = await desktop.call("GET", "/candidate-auth/me", token=desktop.access)
    assert refused.status_code == 401 and refused.json()["code"] == "token-invalid"


async def test_a_code_can_be_resent_once_a_minute(
    client: AsyncClient, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invited_candidate(
        app_db, admin_engine, make_hiring, org, new_device_otp=True
    )
    desktop = Desktop(client)
    challenge = (await desktop.login(email)).json()["challenge_id"]
    resend = "/candidate-auth/otp/resend"
    soon = await desktop.call("POST", resend, json_body={"challenge_id": challenge})
    assert soon.status_code == 429 and int(soon.headers["retry-after"]) > 0
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE candidate_otps SET last_sent_at = now() - interval '2 minutes'")
        )
    later = await desktop.call("POST", resend, json_body={"challenge_id": challenge})
    assert later.status_code == 202
    code = await latest_code(admin_engine, email)
    verified = await desktop.call(
        "POST", "/candidate-auth/otp/verify", json_body={"challenge_id": challenge, "code": code}
    )
    assert verified.status_code == 200
