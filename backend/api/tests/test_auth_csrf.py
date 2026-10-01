"""CSRF protection for cookie-authenticated requests (SP-02 spec, "Sign-in, sessions and CSRF").

A state-changing request that carries the session cookie must come from an allowed Origin and
repeat the CSRF cookie in `X-CSRF-Token`. Sign-in routes need the Origin even without a cookie.
Requests without the cookie elsewhere (bearer-token clients) are left alone.
"""

from collections.abc import Callable

from fastapi import FastAPI
from httpx import AsyncClient

from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.auth.csrf import CsrfMiddleware
from hirevion_api.problems import install_problem_handlers

ORIGIN = "https://app.hirevion.localhost"


def build() -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)
    app.add_middleware(CsrfMiddleware, allowed_origins=frozenset({ORIGIN}))

    @app.get("/api/v1/things")
    async def read_things() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/things")
    async def make_thing() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    return app


def signed_in(client: AsyncClient) -> AsyncClient:
    client.cookies.set(SESSION_COOKIE, "session-token")
    client.cookies.set(CSRF_COOKIE, "csrf-token")
    return client


async def test_a_matching_token_from_the_app_passes(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = signed_in(client_for(build()))
    response = await client.post(
        "/api/v1/things", headers={"Origin": ORIGIN, "X-CSRF-Token": "csrf-token"}
    )
    assert response.status_code == 200


async def test_a_missing_or_wrong_token_is_refused(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = signed_in(client_for(build()))
    missing = await client.post("/api/v1/things", headers={"Origin": ORIGIN})
    wrong = await client.post(
        "/api/v1/things", headers={"Origin": ORIGIN, "X-CSRF-Token": "guessed"}
    )
    for response in (missing, wrong):
        assert response.status_code == 403
        assert response.json()["code"] == "csrf-failed"


async def test_another_origin_is_refused_even_with_the_token(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = signed_in(client_for(build()))
    response = await client.post(
        "/api/v1/things",
        headers={"Origin": "https://evil.example", "X-CSRF-Token": "csrf-token"},
    )
    assert response.status_code == 403


async def test_a_same_origin_referer_stands_in_for_a_missing_origin(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = signed_in(client_for(build()))
    headers = {"Referer": f"{ORIGIN}/account", "X-CSRF-Token": "csrf-token"}
    assert (await client.post("/api/v1/things", headers=headers)).status_code == 200
    bare = await client.post("/api/v1/things", headers={"X-CSRF-Token": "csrf-token"})
    assert bare.status_code == 403


async def test_reading_needs_no_token(client_for: Callable[[FastAPI], AsyncClient]) -> None:
    client = signed_in(client_for(build()))
    assert (await client.get("/api/v1/things")).status_code == 200


async def test_sign_in_routes_need_the_origin_without_a_cookie(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = client_for(build())
    allowed = await client.post("/api/v1/auth/login", headers={"Origin": ORIGIN})
    foreign = await client.post("/api/v1/auth/login", headers={"Origin": "https://evil.example"})
    absent = await client.post("/api/v1/auth/login")
    assert (allowed.status_code, foreign.status_code, absent.status_code) == (200, 403, 403)


async def test_requests_without_the_cookie_are_left_to_their_own_auth(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    response = await client_for(build()).post("/api/v1/things")
    assert response.status_code == 200
