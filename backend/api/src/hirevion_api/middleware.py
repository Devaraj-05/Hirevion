"""Pure ASGI middleware that guards every request before routing.

Each one answers with a problem response itself, so even requests that never reach a route get
the standard error format and security headers.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from opentelemetry import trace
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hirevion_api.problems import SECURITY_HEADERS, internal_error_response, problem_response

log = logging.getLogger(__name__)

_SECURITY_HEADERS = [
    (name.lower().encode(), value.encode()) for name, value in SECURITY_HEADERS.items()
]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return str(value.decode("latin-1"))
    return None


def _host_without_port(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class HostCheckMiddleware:
    """Refuses requests whose Host isn't ours (DNS rebinding, stray traffic)."""

    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            host = _host_without_port(_header(scope, b"host") or "")
            if host not in self.allowed_hosts:
                response = problem_response(
                    400, "host-not-allowed", "Host not allowed", instance=scope.get("path")
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class _BodyTooLarge(HTTPException):
    # An HTTPException, so FastAPI's body parsing re-raises it unchanged and the problem handler
    # answers 413 wherever the limit trips.
    def __init__(self) -> None:
        super().__init__(413, "The request body is larger than this API accepts.")


class BodySizeLimitMiddleware:
    """Refuses bodies over `max_bytes`, whether declared in Content-Length or streamed. A path
    matching one of `upload_limits` (file uploads) may send up to that pattern's limit instead."""

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int,
        upload_limits: Sequence[tuple[re.Pattern[str], int]] = (),
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.upload_limits = tuple(upload_limits)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        limit = next(
            (bytes_ for pattern, bytes_ in self.upload_limits if pattern.fullmatch(path)),
            self.max_bytes,
        )
        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            response = problem_response(
                413,
                "payload-too-large",
                "Payload too large",
                "The request body is larger than this API accepts.",
                instance=scope.get("path"),
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        await self.app(scope, limited_receive, send)


class SecurityHeadersMiddleware:
    """`Cache-Control: no-store` and `nosniff` on every response, unless a route set its own."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers += [header for header in _SECURITY_HEADERS if header[0] not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class UnhandledErrorMiddleware:
    """Turns an unhandled exception into a generic 500 problem, logged once with its traceback."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as error:
            log.exception("Unhandled error in %s %s", scope.get("method"), scope.get("path"))
            span = trace.get_current_span()
            span.record_exception(error)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            if started:
                raise
            await internal_error_response(scope.get("path"))(scope, receive, send)
