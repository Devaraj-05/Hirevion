"""The `Idempotency-Key` header on create endpoints (draft-ietf-httpapi-idempotency-key-header).

A create route takes `Depends(idempotency)` and wraps its work in `Idempotency.run()`:

    return await idem.run(session, org_id, scope, create)

A repeated request (same key, method, path and body) gets the first response again, marked
`Idempotent-Replayed: true`. The same key with a different request is 422
`idempotency-key-reused`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, cast
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.problems import ProblemError
from hirevion_core.idempotency import (
    IdempotencyInProgress,
    IdempotencyKeyReused,
    StoredResponse,
    claim,
    remember,
)

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
_KEY = re.compile(r"[A-Za-z0-9_.:-]{8,255}")


class IdempotentReplay(Exception):
    def __init__(self, stored: StoredResponse) -> None:
        super().__init__("idempotent replay")
        self.stored = stored


@dataclass(frozen=True, slots=True)
class Idempotency:
    key: str
    fingerprint: bytes
    status_code: int

    async def run[M: BaseModel](
        self,
        session: AsyncSession,
        organization_id: UUID,
        scope: str,
        create: Callable[[], Awaitable[M]],
    ) -> M:
        """Run `create` once per key; `scope` identifies the caller (e.g. `user:<id>`)."""
        try:
            stored = await claim(session, organization_id, scope, self.key, self.fingerprint)
        except IdempotencyKeyReused as error:
            raise ProblemError(
                422,
                "idempotency-key-reused",
                "Idempotency key reused",
                "This key was already used for a different request. Send a new key.",
            ) from error
        except IdempotencyInProgress as error:
            raise ProblemError(
                409,
                "idempotency-request-in-progress",
                "Request in progress",
                "A request with this key is still being processed. Retry shortly.",
                headers={"Retry-After": "1"},
            ) from error
        if stored is not None:
            raise IdempotentReplay(stored)
        result = await create()
        body = result.model_dump(mode="json", by_alias=True)
        await remember(session, organization_id, scope, self.key, self.status_code, body)
        return result


async def idempotency(
    request: Request,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias=IDEMPOTENCY_HEADER,
            description=(
                "Required. A unique value (a UUID is ideal) per logical create; "
                "send the same value when retrying it."
            ),
        ),
    ] = None,
) -> Idempotency:
    if idempotency_key is None:
        raise ProblemError(
            400,
            "idempotency-key-missing",
            "Idempotency key missing",
            f"This endpoint needs an {IDEMPOTENCY_HEADER} header.",
        )
    key = idempotency_key.strip()
    if len(key) >= 2 and key[0] == key[-1] == '"':  # the draft's structured-field string form
        key = key[1:-1]
    if not _KEY.fullmatch(key):
        raise ProblemError(
            400,
            "idempotency-key-invalid",
            "Idempotency key invalid",
            "Use 8 to 255 characters from A-Z, a-z, 0-9, '_', '.', ':' and '-'.",
        )
    body = await request.body()
    fingerprint = hashlib.sha256(
        b"\n".join((request.method.encode(), request.url.path.encode(), body))
    ).digest()
    status_code = getattr(request.scope.get("route"), "status_code", None) or 200
    return Idempotency(key, fingerprint, status_code)


async def _replay(request: Request, exc: Exception) -> JSONResponse:
    stored = cast(IdempotentReplay, exc).stored
    return JSONResponse(
        stored.body, status_code=stored.status_code, headers={REPLAYED_HEADER: "true"}
    )


def install_idempotency_handler(app: FastAPI) -> None:
    app.add_exception_handler(IdempotentReplay, _replay)
