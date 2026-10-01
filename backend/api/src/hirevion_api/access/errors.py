"""Access refusals as RFC 9457 problems (ADR-0010), with a field error when one input is at
fault, in the same shape as validation problems."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from hirevion_api.problems import problem_response
from hirevion_core.access.errors import AccessError


async def _access_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast(AccessError, exc)
    extensions: dict[str, Any] = {}
    if error.field is not None:
        extensions["errors"] = [{"detail": error.title, "pointer": f"#/{error.field}"}]
    return problem_response(
        error.status,
        error.code,
        error.title,
        error.detail,
        instance=request.url.path,
        **extensions,
    )


def install_access_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AccessError, _access_error)
