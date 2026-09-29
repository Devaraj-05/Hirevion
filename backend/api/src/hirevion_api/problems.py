"""RFC 9457 problem details: the one error format every endpoint returns (ADR-0010).

A problem's `type` is `urn:hirevion:problem:<code>`, and `code` repeats the slug for clients
that switch on it. `trace_id` links the response to its trace. Bodies never carry exception
text, SQL or secrets: unhandled errors are logged and answered with a generic 500.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
SECURITY_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

# Problem codes for errors raised by the framework rather than by our code.
_HTTP_CODES = {
    400: "bad-request",
    404: "not-found",
    405: "method-not-allowed",
    413: "payload-too-large",
}


class Problem(BaseModel):
    """An RFC 9457 problem; codes may add extension members (e.g. `errors`, `checks`)."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str
    trace_id: str | None = None


class ProblemError(Exception):
    """Raise to answer with a problem; `extensions` become extra members of the body."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        headers: Mapping[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = dict(headers or {})
        self.extensions = extensions


def problem_type(code: str) -> str:
    return f"urn:hirevion:problem:{code}"


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def problem_response(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    *,
    instance: str | None = None,
    headers: Mapping[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    body: dict[str, Any] = {"type": problem_type(code), "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    body |= {"code": code, "trace_id": current_trace_id(), **extensions}
    return JSONResponse(
        body,
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers={**SECURITY_HEADERS, **(headers or {})},
    )


def internal_error_response(instance: str | None) -> JSONResponse:
    return problem_response(
        500,
        "internal-error",
        "Internal server error",
        "Something went wrong on our side. Quote the trace id if you contact support.",
        instance=instance,
    )


def _escape_pointer(part: object) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def _validation_entry(error: Mapping[str, Any]) -> dict[str, str]:
    location: Sequence[Any] = error.get("loc", ())
    detail = str(error.get("msg", "Invalid value"))
    where, rest = (location[0], location[1:]) if location else ("", ())
    if where == "body":
        return {
            "pointer": "#" + "".join("/" + _escape_pointer(part) for part in rest),
            "detail": detail,
        }
    if where in ("query", "path"):
        return {"parameter": str(rest[0]) if rest else "", "detail": detail}
    if where in ("header", "cookie"):
        return {where: str(rest[0]) if rest else "", "detail": detail}
    return {"detail": detail}


# Starlette types every handler as (Request, Exception); each is registered for one class.
async def _problem_error(request: Request, exc: Exception) -> JSONResponse:
    problem = cast(ProblemError, exc)
    return problem_response(
        problem.status,
        problem.code,
        problem.title,
        problem.detail,
        instance=request.url.path,
        headers=problem.headers,
        **problem.extensions,
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    errors = cast(RequestValidationError, exc).errors()
    return problem_response(
        422,
        "validation-failed",
        "Validation failed",
        "The request doesn't match the schema; see `errors`.",
        instance=request.url.path,
        errors=[_validation_entry(error) for error in errors],
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast(StarletteHTTPException, exc)
    title = HTTPStatus(error.status_code).phrase
    detail = error.detail if isinstance(error.detail, str) and error.detail != title else None
    return problem_response(
        error.status_code,
        _HTTP_CODES.get(error.status_code, "http-error"),
        title,
        detail,
        instance=request.url.path,
        headers=error.headers,
    )


def install_problem_handlers(app: FastAPI) -> None:
    """Answer every handled error as a problem (unhandled ones: `UnhandledErrorMiddleware`)."""
    app.add_exception_handler(ProblemError, _problem_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
