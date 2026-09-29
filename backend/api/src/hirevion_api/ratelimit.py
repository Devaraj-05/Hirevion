"""Rate limits over HTTP: a global per-IP limit and per-route rules (ADR-0010).

Responses carry `RateLimit-Policy` and `RateLimit` (draft-ietf-httpapi-ratelimit-headers), one
list item per rule that applied. A refused request is a 429 `rate-limited` problem with
`Retry-After`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hirevion_api.deps import client_ip
from hirevion_api.problems import ProblemError, problem_response
from hirevion_api.routing import API_PREFIX
from hirevion_core.ratelimit import RateDecision, RateLimiter, RateRule

log = logging.getLogger(__name__)

# How long a request waits for Valkey before the limit is skipped (or refused, if fail-closed).
BUDGET_SECONDS = 0.25
_EXEMPT_PREFIX = f"{API_PREFIX}/health/"
_POLICY = "RateLimit-Policy"
_STATE = "RateLimit"


class RateLimiterUnavailable(Exception):
    pass


def rate_headers(rule: RateRule, decision: RateDecision) -> dict[str, str]:
    return {
        _POLICY: f'"{rule.name}";q={rule.limit};w={rule.period_seconds}',
        _STATE: f'"{rule.name}";r={decision.remaining};t={decision.reset_seconds}',
    }


async def check(redis: Redis, rule: RateRule, subject: str) -> RateDecision | None:
    """The decision, or `None` when Valkey didn't answer and the rule fails open."""
    try:
        async with asyncio.timeout(BUDGET_SECONDS):
            return await RateLimiter(redis).hit(rule, subject)
    except (RedisError, OSError, TimeoutError) as error:
        if rule.fail_closed:
            raise RateLimiterUnavailable(rule.name) from error
        log.warning("Rate limit %s skipped: Valkey is unavailable (%s)", rule.name, error)
        return None


def _refusal(rule: RateRule, decision: RateDecision) -> tuple[str, str, str, dict[str, str]]:
    headers = rate_headers(rule, decision) | {"Retry-After": str(decision.retry_after_seconds)}
    detail = f"Too many requests. Retry in {decision.retry_after_seconds} s."
    return "rate-limited", "Too many requests", detail, headers


_UNAVAILABLE = (
    "service-unavailable",
    "Service unavailable",
    "Rate limiting is unavailable, so this request can't be accepted now.",
)


def by_ip(request: Request) -> str:
    return client_ip(request)


def rate_limited(
    rule: RateRule, key: Callable[[Request], str] = by_ip
) -> Callable[[Request, Response], Awaitable[None]]:
    """A route dependency that applies `rule` to the subject `key` picks from the request."""

    async def dependency(request: Request, response: Response) -> None:
        redis: Redis | None = request.app.state.redis
        if redis is None:
            return
        try:
            decision = await check(redis, rule, key(request))
        except RateLimiterUnavailable as error:
            raise ProblemError(503, *_UNAVAILABLE) from error
        if decision is None:
            return
        if not decision.allowed:
            code, title, detail, headers = _refusal(rule, decision)
            raise ProblemError(429, code, title, detail, headers=headers)
        response.headers.update(rate_headers(rule, decision))

    return dependency


class RateLimitMiddleware:
    """The global limit: `rule` per client IP on every route except the health checks."""

    def __init__(self, app: ASGIApp, rule: RateRule) -> None:
        self.app = app
        self.rule = rule

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Starlette puts the application in the scope; its state holds the Valkey client.
        redis: Redis | None = getattr(getattr(scope.get("app"), "state", None), "redis", None)
        if scope["type"] != "http" or redis is None or scope["path"].startswith(_EXEMPT_PREFIX):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        subject = client[0] if client else "unknown"
        try:
            decision = await check(redis, self.rule, subject)
        except RateLimiterUnavailable:
            await problem_response(503, *_UNAVAILABLE, instance=scope["path"])(scope, receive, send)
            return
        if decision is None:
            await self.app(scope, receive, send)
            return
        if not decision.allowed:
            code, title, detail, headers = _refusal(self.rule, decision)
            response = problem_response(
                429, code, title, detail, instance=scope["path"], headers=headers
            )
            await response(scope, receive, send)
            return

        ours = rate_headers(self.rule, decision)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = _merge(list(message.get("headers", [])), ours)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _merge(headers: list[tuple[bytes, bytes]], ours: dict[str, str]) -> list[tuple[bytes, bytes]]:
    """Put the global rule first in each RateLimit list, before any route rule's item."""
    merged = list(headers)
    for name, value in ours.items():
        raw_name = name.lower().encode()
        existing = [item for item in merged if item[0].lower() == raw_name]
        merged = [item for item in merged if item[0].lower() != raw_name]
        combined = ", ".join([value, *(item[1].decode("latin-1") for item in existing)])
        merged.append((raw_name, combined.encode("latin-1")))
    return merged
