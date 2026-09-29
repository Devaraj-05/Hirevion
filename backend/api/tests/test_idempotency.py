"""`Idempotency-Key` on creates (master plan §13; draft-ietf-httpapi-idempotency-key-header)."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.deps import get_db
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.problems import ProblemError
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.outbox import publish_event

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("empty_outbox")]

MakeOrganization = Callable[[str], Awaitable[UUID]]
router = APIRouter(prefix="/api/v1/test")


class WidgetIn(BaseModel):
    name: str


class WidgetOut(BaseModel):
    id: UUID
    name: str


@router.post("/orgs/{org_id}/widgets", status_code=201)
async def create_widget(
    org_id: UUID,
    body: WidgetIn,
    idem: Annotated[Idempotency, Depends(idempotency)],
    db: Annotated[Database, Depends(get_db)],
) -> WidgetOut:
    async with db.tenant(org_id) as session:

        async def create() -> WidgetOut:
            event_id = await publish_event(session, org_id, "widget.created", {"name": body.name})
            if body.name == "clash":
                raise ProblemError(409, "widget-clash", "Widget clash")
            return WidgetOut(id=event_id, name=body.name)

        return await idem.run(session, org_id, "test", create)


@pytest.fixture
def client(
    app_db: Database, valkey: Redis, client_for: Callable[[FastAPI], AsyncClient]
) -> AsyncClient:
    app = create_app(ApiSettings(), db=app_db, redis=valkey)
    app.include_router(router)
    return client_for(app)


async def events(admin_engine: AsyncEngine, org: UUID) -> int:
    async with admin_engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM outbox_events WHERE organization_id = :org"), {"org": org}
        )
    return int(count or 0)


async def test_the_key_is_required_and_checked(
    client: AsyncClient, make_organization: MakeOrganization
) -> None:
    url = f"/api/v1/test/orgs/{await make_organization('IdemApi')}/widgets"
    missing = await client.post(url, json={"name": "a"})
    assert missing.status_code == 400
    assert missing.json()["code"] == "idempotency-key-missing"
    for bad in ("a b c d e f", "short", "x" * 300):
        response = await client.post(url, json={"name": "a"}, headers={"Idempotency-Key": bad})
        assert response.status_code == 400
        assert response.json()["code"] == "idempotency-key-invalid"


async def test_a_retry_replays_the_first_response(
    client: AsyncClient, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemReplay")
    url, headers = f"/api/v1/test/orgs/{org}/widgets", {"Idempotency-Key": "retry-0001"}
    first = await client.post(url, json={"name": "a"}, headers=headers)
    second = await client.post(url, json={"name": "a"}, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "idempotent-replayed" not in first.headers
    assert second.headers["idempotent-replayed"] == "true"
    assert await events(admin_engine, org) == 1


async def test_the_same_key_for_another_request_is_refused(
    client: AsyncClient, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemOther")
    url, headers = f"/api/v1/test/orgs/{org}/widgets", {"Idempotency-Key": "reuse-0001"}
    await client.post(url, json={"name": "a"}, headers=headers)
    response = await client.post(url, json={"name": "b"}, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "idempotency-key-reused"


async def test_a_failed_request_is_not_remembered(
    client: AsyncClient, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemFail")
    url, headers = f"/api/v1/test/orgs/{org}/widgets", {"Idempotency-Key": "fail-0001"}
    for _ in range(2):
        response = await client.post(url, json={"name": "clash"}, headers=headers)
        assert response.status_code == 409
        assert response.json()["code"] == "widget-clash"
        assert "idempotent-replayed" not in response.headers
    assert await events(admin_engine, org) == 0


async def test_quoted_and_bare_keys_are_the_same_key(
    client: AsyncClient, make_organization: MakeOrganization
) -> None:
    url = f"/api/v1/test/orgs/{await make_organization('IdemQuoted')}/widgets"
    await client.post(url, json={"name": "a"}, headers={"Idempotency-Key": '"quoted-0001"'})
    again = await client.post(url, json={"name": "a"}, headers={"Idempotency-Key": "quoted-0001"})
    assert again.headers["idempotent-replayed"] == "true"


def test_the_header_is_documented() -> None:
    app = create_app(ApiSettings())
    app.include_router(router)
    parameters = app.openapi()["paths"]["/api/v1/test/orgs/{org_id}/widgets"]["post"]["parameters"]
    assert {"name": "Idempotency-Key", "in": "header"}.items() <= parameters[-1].items()
