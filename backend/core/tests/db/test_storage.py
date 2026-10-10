"""Blob storage against Azurite (the local stack, or the CI container)."""

import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from hirevion_core.ids import uuid7
from hirevion_core.storage.paths import interview_blob, job_blob
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings

pytestmark = pytest.mark.db

WEB_ORIGIN = "https://app.hirevion.localhost"


@pytest.fixture
async def storage() -> AsyncIterator[StorageService]:
    settings = load_storage_settings()
    # Straight to Azurite: tests don't go through Caddy's TLS, which CI doesn't have.
    direct = settings.model_copy(update={"storage_public_endpoint": settings.internal_endpoint})
    await ensure_storage(direct, [WEB_ORIGIN])
    service = StorageService(direct)
    yield service
    await service.aclose()


async def test_blobs_round_trip(storage: StorageService) -> None:
    path = job_blob(uuid7(), uuid7(), "jd.txt")
    await storage.put(path, b"Senior Python engineer", "text/plain")
    assert await storage.exists(path)
    assert await storage.get(path) == b"Senior Python engineer"
    await storage.delete(path)
    assert not await storage.exists(path)
    await storage.delete(path)  # deleting twice is fine


async def test_an_upload_url_writes_but_cannot_read(storage: StorageService) -> None:
    org = uuid7()
    path = interview_blob(org, uuid7(), "screen", "seg-000001.mp4")
    url = storage.upload_url(org, path)
    async with httpx.AsyncClient() as http:
        stored = await http.put(url, content=b"segment", headers={"x-ms-blob-type": "BlockBlob"})
        assert stored.status_code == 201
        assert (await http.get(url)).status_code == 403
    assert await storage.get(path) == b"segment"


async def test_a_download_url_reads_as_an_attachment(storage: StorageService) -> None:
    org = uuid7()
    path = interview_blob(org, uuid7(), "report", "report.pdf")
    await storage.put(path, b"%PDF-1.7", "application/pdf")
    async with httpx.AsyncClient() as http:
        response = await http.get(storage.download_url(org, path, filename="report.pdf"))
    assert response.status_code == 200
    assert response.content == b"%PDF-1.7"
    assert 'filename="report.pdf"' in response.headers["content-disposition"]


async def test_expired_urls_are_refused(storage: StorageService) -> None:
    org = uuid7()
    path = job_blob(org, uuid7(), "late.txt")
    url = storage.upload_url(org, path, expires=timedelta(seconds=-60))
    async with httpx.AsyncClient() as http:
        response = await http.put(url, content=b"x", headers={"x-ms-blob-type": "BlockBlob"})
    assert response.status_code == 403


async def test_the_container_is_private(storage: StorageService) -> None:
    org = uuid7()
    path = job_blob(org, uuid7(), "private.txt")
    await storage.put(path, b"secret", "text/plain")
    anonymous = (
        f"{storage.settings.internal_endpoint}/{storage.settings.azure_storage_container}/{path}"
    )
    async with httpx.AsyncClient() as http:
        response = await http.get(anonymous)
    assert response.status_code in (401, 403, 404)
    assert b"secret" not in response.content


async def test_setup_is_idempotent_and_allows_browser_uploads(storage: StorageService) -> None:
    await ensure_storage(storage.settings, [WEB_ORIGIN])
    org = uuid7()
    url = storage.upload_url(org, job_blob(org, uuid7(), "resume.pdf"))
    async with httpx.AsyncClient() as http:
        preflight = await http.options(
            url,
            headers={
                "Origin": WEB_ORIGIN,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "x-ms-blob-type,content-type",
            },
        )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == WEB_ORIGIN


async def test_a_blob_can_be_hashed_without_holding_it_in_memory(storage: StorageService) -> None:
    path = interview_blob(uuid7(), uuid7(), "screen", "screen-1-000001.mp4")
    data = b"0123456789" * 300_000  # 3 MB: several chunks
    await storage.put(path, data, "video/mp4")
    assert await storage.digest(path) == (len(data), hashlib.sha256(data).hexdigest())
    await storage.delete(path)
    assert await storage.digest(path) is None


async def test_files_stream_to_and_from_blobs(storage: StorageService, tmp_path: Path) -> None:
    path = interview_blob(uuid7(), uuid7(), "camera", "camera-full.webm")
    source = tmp_path / "source.bin"
    source.write_bytes(b"\x1aE\xdf\xa3" * 100_000)
    await storage.upload_file(path, source, "video/webm")
    target = tmp_path / "target.bin"
    await storage.download_to(path, target)
    assert target.read_bytes() == source.read_bytes()
    await storage.delete(path)
    with pytest.raises(FileNotFoundError):
        await storage.download_to(path, tmp_path / "missing.bin")
