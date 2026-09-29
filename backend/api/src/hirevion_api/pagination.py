"""Cursor (keyset) pagination: `?limit=&cursor=` in, `{items, next_cursor}` out (ADR-0010).

A cursor is opaque to clients: URL-safe base64 of `{"v": 1, "o": <ordering>, "k": [<values>]}`,
where the values are the sort keys of the last row returned. Pages stay stable while rows are
added, and a cursor only works for the ordering that produced it. Sort columns must be NOT NULL
and end with a unique column (normally `id`).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, literal, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from hirevion_api.problems import ProblemError

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
_VERSION = 1

CursorValue = UUID | datetime | date | Decimal | bool | int | str | None


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    cursor: str | None


def page_params(
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="How many items to return.")
    ] = DEFAULT_LIMIT,
    cursor: Annotated[
        str | None, Query(max_length=1024, description="`next_cursor` from the previous page.")
    ] = None,
) -> PageParams:
    return PageParams(limit, cursor)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )


def _invalid_cursor() -> ProblemError:
    return ProblemError(
        400,
        "invalid-cursor",
        "Invalid cursor",
        "The cursor doesn't belong to this list. Start again without one.",
    )


def _tag(value: CursorValue) -> Any:
    if isinstance(value, UUID):
        return {"u": str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("cursor datetimes must carry a time zone")
        return {"t": value.isoformat()}
    if isinstance(value, date):
        return {"d": value.isoformat()}
    if isinstance(value, Decimal):
        return {"n": str(value)}
    if value is None or isinstance(value, bool | int | str):
        return value
    raise TypeError(f"a {type(value).__name__} can't go into a cursor")


def _untag(value: Any) -> CursorValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if not (isinstance(value, dict) and len(value) == 1):
        raise ValueError("unknown cursor value")
    ((tag, raw),) = value.items()
    if not isinstance(raw, str):
        raise ValueError("unknown cursor value")
    if tag == "u":
        return UUID(raw)
    if tag == "t":
        moment = datetime.fromisoformat(raw)
        if moment.tzinfo is None:
            raise ValueError("cursor datetimes must carry a time zone")
        return moment
    if tag == "d":
        return date.fromisoformat(raw)
    if tag == "n":
        number = Decimal(raw)
        if not number.is_finite():
            raise ValueError("cursor numbers must be finite")
        return number
    raise ValueError("unknown cursor value")


def encode_cursor(order: str, values: Sequence[CursorValue]) -> str:
    payload = {"v": _VERSION, "o": order, "k": [_tag(value) for value in values]}
    text = json.dumps(payload, separators=(",", ":"))
    return base64.urlsafe_b64encode(text.encode("utf-8")).rstrip(b"=").decode("ascii")


def decode_cursor(order: str, cursor: str) -> list[CursorValue]:
    """The sort-key values in `cursor`; `invalid-cursor` if it isn't one for `order`."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw)
        if not (
            isinstance(payload, dict)
            and payload.get("v") == _VERSION
            and payload.get("o") == order
            and isinstance(payload.get("k"), list)
        ):
            raise ValueError("not a cursor for this ordering")
        return [_untag(value) for value in payload["k"]]
    except (ValueError, TypeError, ArithmeticError, binascii.Error) as error:
        raise _invalid_cursor() from error


def order_signature(order_by: Sequence[InstrumentedAttribute[Any]], descending: bool) -> str:
    return ",".join(column.key for column in order_by) + (":desc" if descending else ":asc")


async def paginate[T](
    session: AsyncSession,
    statement: Select[T],
    order_by: Sequence[InstrumentedAttribute[Any]],
    params: PageParams,
    *,
    descending: bool = False,
) -> tuple[list[T], str | None]:
    """One page of `statement`'s entities in `order_by` order, and the cursor for the next."""
    order = order_signature(order_by, descending)
    if params.cursor is not None:
        values = decode_cursor(order, params.cursor)
        if len(values) != len(order_by):
            raise _invalid_cursor()
        keys = tuple_(*order_by)
        after = tuple_(
            *(literal(value, column.type) for column, value in zip(order_by, values, strict=True))
        )
        statement = statement.where(keys < after if descending else keys > after)
    ordering = [column.desc() if descending else column.asc() for column in order_by]
    rows = list(
        (await session.scalars(statement.order_by(*ordering).limit(params.limit + 1))).all()
    )
    if len(rows) <= params.limit:
        return rows, None
    rows = rows[: params.limit]
    return rows, encode_cursor(order, [getattr(rows[-1], column.key) for column in order_by])
