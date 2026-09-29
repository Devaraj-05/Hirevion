import base64
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from hirevion_api.app import create_app
from hirevion_api.pagination import Page, PageParams, decode_cursor, encode_cursor, page_params
from hirevion_api.problems import ProblemError
from hirevion_api.settings import ApiSettings

ORDER = "created_at,id:asc"
VALUES = [
    datetime(2026, 9, 29, 10, 30, 0, 123456, tzinfo=UTC),
    UUID("01920000-0000-7000-8000-0000000000aa"),
    date(2026, 9, 29),
    Decimal("12.50"),
    42,
    "Acme",
    None,
]


def raw_cursor(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()


def test_cursors_round_trip_typed_values() -> None:
    decoded = decode_cursor(ORDER, encode_cursor(ORDER, VALUES))
    assert decoded == VALUES
    assert [type(value) for value in decoded] == [type(value) for value in VALUES]


def test_cursors_are_url_safe_without_padding() -> None:
    assert re.fullmatch(r"[A-Za-z0-9_-]+", encode_cursor(ORDER, VALUES))


def test_a_cursor_fits_only_its_ordering() -> None:
    with pytest.raises(ProblemError) as error:
        decode_cursor("id:asc", encode_cursor(ORDER, VALUES))
    assert error.value.status == 400
    assert error.value.code == "invalid-cursor"


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!!!",
        raw_cursor(["not", "an", "object"]),
        raw_cursor({"v": 2, "o": ORDER, "k": []}),
        raw_cursor({"v": 1, "o": ORDER, "k": "x"}),
        raw_cursor({"v": 1, "o": ORDER, "k": [{"u": "not-a-uuid"}]}),
        raw_cursor({"v": 1, "o": ORDER, "k": [{"t": "2026-09-29T10:30:00"}]}),
        raw_cursor({"v": 1, "o": ORDER, "k": [{"n": "NaN-ish"}]}),
        raw_cursor({"v": 1, "o": ORDER, "k": [{"x": "1"}]}),
        base64.urlsafe_b64encode(b"not json").decode(),
    ],
)
def test_malformed_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(ProblemError) as error:
        decode_cursor(ORDER, cursor)
    assert error.value.code == "invalid-cursor"


def test_naive_datetimes_cannot_go_into_a_cursor() -> None:
    with pytest.raises(ValueError, match="time zone"):
        encode_cursor(ORDER, [datetime(2026, 9, 29, 10, 30)])


class Item(BaseModel):
    name: str


router = APIRouter(prefix="/api/v1/test")


@router.get("/items")
async def list_items(params: Annotated[PageParams, Depends(page_params)]) -> Page[Item]:
    if params.cursor is not None:
        decode_cursor("id:asc", params.cursor)
    return Page[Item](items=[Item(name="a")][: params.limit], next_cursor=None)


@pytest.fixture
def client(client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    app = create_app(ApiSettings())
    app.include_router(router)
    return client_for(app)


async def test_limit_is_validated(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/test/items")).json() == {
        "items": [{"name": "a"}],
        "next_cursor": None,
    }
    for bad in ("0", "101", "x"):
        response = await client.get(f"/api/v1/test/items?limit={bad}")
        assert response.status_code == 422
        assert response.json()["errors"][0]["parameter"] == "limit"


async def test_a_bad_cursor_is_a_400_problem(client: AsyncClient) -> None:
    response = await client.get("/api/v1/test/items?cursor=garbage")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid-cursor"
