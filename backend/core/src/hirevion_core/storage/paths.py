"""Blob names as PRD §85 lays them out, always under the owning organisation:

    {organization_id}/jobs/{job_id}/{file}
    {organization_id}/candidates/{candidate_id}/{file}
    {organization_id}/interviews/{interview_id}/{screen|camera|audio|third-eye|evidence|transcript|report}/{file}

Build paths only with these helpers: they validate every part, so no caller-supplied text can
climb out of its organisation's prefix.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, get_args
from uuid import UUID

InterviewArtifact = Literal[
    "screen", "camera", "audio", "third-eye", "evidence", "transcript", "report"
]
_ARTIFACTS = frozenset(get_args(InterviewArtifact))
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")


def safe_filename(filename: str) -> str:
    if not _FILENAME.fullmatch(filename) or ".." in filename:
        raise ValueError(f"not a safe file name: {filename!r}")
    return filename


def download_name(original: str | None, fallback: str) -> str:
    """A file name safe to offer for a download, as close to the name a person gave as the rules
    for `safe_filename` allow: accents dropped, other characters made underscores. Nothing usable
    left (a name in another script, only dots) gives `fallback`, with the original extension."""
    plain = unicodedata.normalize("NFKD", original or "").encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", plain)
    stem, dot, ending = cleaned.rpartition(".")
    if not dot:
        stem, ending = cleaned, ""
    extension = f".{ending}" if re.fullmatch(r"[A-Za-z0-9]{1,8}", ending) else ""
    stem = stem.strip("._-")[:150] or fallback
    return f"{stem}{extension}"


@dataclass(frozen=True, slots=True)
class BlobPath:
    organization_id: UUID
    key: str

    def __str__(self) -> str:
        return f"{self.organization_id}/{self.key}"


def job_blob(organization_id: UUID, job_id: UUID, filename: str) -> BlobPath:
    return BlobPath(organization_id, f"jobs/{job_id}/{safe_filename(filename)}")


def candidate_blob(organization_id: UUID, candidate_id: UUID, filename: str) -> BlobPath:
    return BlobPath(organization_id, f"candidates/{candidate_id}/{safe_filename(filename)}")


def interview_blob(
    organization_id: UUID, interview_id: UUID, kind: InterviewArtifact, filename: str
) -> BlobPath:
    if kind not in _ARTIFACTS:
        raise ValueError(f"unknown interview artifact kind: {kind!r}")
    return BlobPath(organization_id, f"interviews/{interview_id}/{kind}/{safe_filename(filename)}")
