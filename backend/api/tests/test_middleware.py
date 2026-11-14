from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, FastAPI, Request
from httpx import AsyncClient

from hirevion_api.app import create_app
from hirevion_api.deps import client_ip
from hirevion_api.settings import ApiSettings

router = APIRouter(prefix="/api/v1/test")


@router.get("/ip")
async def ip(request: Request) -> dict[str, str]:
    return {"ip": client_ip(request)}


@router.post("/echo")
async def echo(request: Request) -> dict[str, int]:
    return {"size": len(await request.body())}


def client_with(client_for: Callable[[FastAPI], AsyncClient], **settings: object) -> AsyncClient:
    app = create_app(ApiSettings(**settings))  # type: ignore[arg-type]
    app.include_router(router)
    return client_for(app)


async def test_unknown_hosts_are_refused(client_for: Callable[[FastAPI], AsyncClient]) -> None:
    client = client_with(client_for)
    response = await client.get("/api/v1/health/live", headers={"host": "evil.example"})
    assert response.status_code == 400
    assert response.json()["code"] == "host-not-allowed"
    ok = await client.get("/api/v1/health/live", headers={"host": "LOCALHOST:8000"})
    assert ok.status_code == 200


async def test_large_bodies_are_refused(client_for: Callable[[FastAPI], AsyncClient]) -> None:
    client = client_with(client_for, max_body_bytes=10)

    declared = await client.post("/api/v1/test/echo", content=b"x" * 11)
    assert declared.status_code == 413
    assert declared.json()["code"] == "payload-too-large"

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"xxxx"

    streamed = await client.post("/api/v1/test/echo", content=chunks())
    assert streamed.status_code == 413
    assert streamed.json()["code"] == "payload-too-large"

    fits = await client.post("/api/v1/test/echo", content=b"x" * 10)
    assert fits.json() == {"size": 10}


async def test_security_headers_are_on_every_response(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = client_with(client_for)
    for path in ("/api/v1/health/live", "/api/v1/nothing-here"):
        response = await client.get(path)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


async def test_forwarded_for_is_trusted_only_from_proxies(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    forwarded = {"x-forwarded-for": "203.0.113.9"}
    trusting = client_with(client_for)
    assert (await trusting.get("/api/v1/test/ip", headers=forwarded)).json() == {
        "ip": "203.0.113.9"
    }
    wary = client_with(client_for, trusted_proxies="10.0.0.1")
    assert (await wary.get("/api/v1/test/ip", headers=forwarded)).json() == {"ip": "127.0.0.1"}


async def test_upload_routes_take_larger_bodies(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = client_with(client_for, max_body_bytes=10, max_upload_bytes=100)
    upload = "/api/v1/jobs/0190f1a2-0000-7000-8000-000000000000/jd"

    fits = await client.post(upload, content=b"x" * 100)
    assert fits.status_code != 413
    too_large = await client.post(upload, content=b"x" * 101)
    assert too_large.status_code == 413
    elsewhere = await client.post("/api/v1/test/echo", content=b"x" * 11)
    assert elsewhere.status_code == 413


async def test_resume_uploads_take_zip_archives(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    client = client_with(
        client_for, max_body_bytes=10, max_upload_bytes=100, max_archive_upload_bytes=200
    )
    resumes = "/api/v1/jobs/0190f1a2-0000-7000-8000-000000000000/resumes"
    description = "/api/v1/jobs/0190f1a2-0000-7000-8000-000000000000/jd"

    assert (await client.post(resumes, content=b"x" * 200)).status_code != 413
    assert (await client.post(resumes, content=b"x" * 201)).status_code == 413
    assert (await client.post(description, content=b"x" * 150)).status_code == 413


async def test_trace_headers_longer_than_the_w3c_limit_never_reach_the_app() -> None:
    """GHSA-xcq7-p3pf-p88h and GHSA-mf5v-w3w3-f6cg: OpenTelemetry parses `tracestate` and
    `traceparent` in quadratic time, so a long header stalls the worker. The guard drops either
    header when it is longer than 512 characters and keeps normal ones."""
    from hirevion_api.middleware import TraceStateGuard

    seen: list[list[tuple[bytes, bytes]]] = []

    async def app(scope: dict[str, object], receive: object, send: object) -> None:
        seen.append(list(scope["headers"]))  # type: ignore[call-overload]

    guard = TraceStateGuard(app)  # type: ignore[arg-type]
    parent = b"00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    long_value = b"00-" + b" " * 100_000 + b"x"
    await guard(
        {"type": "http", "headers": [(b"traceparent", long_value), (b"tracestate", long_value)]},
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    # uvicorn's websocket protocols keep the client's header case; OpenTelemetry matches any case.
    await guard(
        {
            "type": "websocket",
            "headers": [(b"Traceparent", long_value), (b"TraceState", long_value)],
        },
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    await guard(
        {"type": "http", "headers": [(b"traceparent", parent), (b"tracestate", b"vendor=v1")]},
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    assert seen[0] == []
    assert seen[1] == []
    assert seen[2] == [(b"traceparent", parent), (b"tracestate", b"vendor=v1")]
