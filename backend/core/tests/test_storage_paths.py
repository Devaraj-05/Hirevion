"""Blob paths follow PRD §85, and signed URLs are narrow and short-lived."""

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from hirevion_core.storage.paths import candidate_blob, interview_blob, job_blob
from hirevion_core.storage.service import StorageService, StorageSettings

ORG = UUID("01920000-0000-7000-8000-000000000001")
OTHER_ORG = UUID("01920000-0000-7000-8000-000000000002")
INTERVIEW = UUID("01920000-0000-7000-8000-0000000000aa")
JOB = UUID("01920000-0000-7000-8000-0000000000bb")
CANDIDATE = UUID("01920000-0000-7000-8000-0000000000cc")
KEY = base64.b64encode(b"k" * 64).decode()


def test_blob_paths_follow_the_prd_layout() -> None:
    screen = interview_blob(ORG, INTERVIEW, "screen", "seg-000001.mp4")
    assert str(screen) == f"{ORG}/interviews/{INTERVIEW}/screen/seg-000001.mp4"
    assert screen.organization_id == ORG
    assert str(interview_blob(ORG, INTERVIEW, "third-eye", "seg-000001.mp4")).endswith(
        "/third-eye/seg-000001.mp4"
    )
    assert str(job_blob(ORG, JOB, "jd.pdf")) == f"{ORG}/jobs/{JOB}/jd.pdf"
    assert str(candidate_blob(ORG, CANDIDATE, "resume.pdf")) == (
        f"{ORG}/candidates/{CANDIDATE}/resume.pdf"
    )


@pytest.mark.parametrize(
    "filename", ["", "..", "../x", "a/b", "a\\b", ".hidden", "x" * 201, "bad\x00name", "sp ace"]
)
def test_unsafe_filenames_are_refused(filename: str) -> None:
    with pytest.raises(ValueError, match="file name"):
        job_blob(ORG, JOB, filename)


def test_unknown_artifact_kinds_are_refused() -> None:
    with pytest.raises(ValueError, match="artifact"):
        interview_blob(ORG, INTERVIEW, "desktop", "x.mp4")  # type: ignore[arg-type]


def service() -> StorageService:
    return StorageService(
        StorageSettings(azure_storage_account="hirevion", azure_storage_key=KEY)  # type: ignore[arg-type]
    )


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def expiry(url: str) -> datetime:
    return datetime.fromisoformat(query(url)["se"][0].replace("Z", "+00:00"))


def test_upload_urls_are_write_only_and_short_lived() -> None:
    path = interview_blob(ORG, INTERVIEW, "screen", "seg-000001.mp4")
    url = service().upload_url(ORG, path)
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc) == ("https", "storage.hirevion.localhost")
    assert parts.path == f"/hirevion/hirevion/{path}"
    assert query(url)["sp"] == ["cw"]
    assert query(url)["sr"] == ["b"]
    now = datetime.now(UTC)
    assert now < expiry(url) <= now + timedelta(minutes=15, seconds=5)


def test_the_protocol_follows_what_the_storage_service_receives() -> None:
    path = job_blob(ORG, JOB, "jd.pdf")
    # Locally Caddy terminates TLS and forwards plain HTTP to Azurite.
    assert query(service().upload_url(ORG, path))["spr"] == ["https,http"]
    # In Azure the storage service itself receives the HTTPS request.
    cloud = StorageService(
        StorageSettings(  # type: ignore[arg-type]
            azure_storage_account="hirevion",
            azure_storage_key=KEY,
            azure_storage_endpoint="https://hirevion.blob.core.windows.net",
            storage_public_endpoint="https://hirevion.blob.core.windows.net",
        )
    )
    assert query(cloud.upload_url(ORG, path))["spr"] == ["https"]


def test_download_urls_are_read_only_and_shorter_lived() -> None:
    path = interview_blob(ORG, INTERVIEW, "report", "report.pdf")
    url = service().download_url(ORG, path, filename="report.pdf")
    assert query(url)["sp"] == ["r"]
    assert query(url)["rscd"] == ['attachment; filename="report.pdf"']
    now = datetime.now(UTC)
    assert now < expiry(url) <= now + timedelta(minutes=5, seconds=5)


def test_another_organisations_blob_is_never_signed() -> None:
    path = job_blob(ORG, JOB, "jd.pdf")
    with pytest.raises(ValueError, match="organisation"):
        service().upload_url(OTHER_ORG, path)
    with pytest.raises(ValueError, match="organisation"):
        service().download_url(OTHER_ORG, path)


def test_download_filenames_are_checked_too() -> None:
    with pytest.raises(ValueError, match="file name"):
        service().download_url(ORG, job_blob(ORG, JOB, "jd.pdf"), filename='x"; evil=1')
