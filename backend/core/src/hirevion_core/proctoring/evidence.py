"""The evidence manager (PRD §54's fifth stage, §67).

- **Snapshots:** the desktop asks for an upload slot (a write-only URL for one blob that lives five
  minutes), uploads the image and names the blob in the event's `evidence`. A slot is a row with
  no event until an event claims it. A claimed slot can't be given out again, so evidence can't be
  replaced after the fact.
- **Server evidence:** for an event worth a reviewer's attention the server adds references of its
  own: the process's metadata, the transcript around it, and the window of the recording that
  covers it (SP-12 resolves the window to segments). Nothing here stores media.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Conflict, Invalid, TooLarge
from hirevion_core.models import ProctorEvent, ProctorEvidence, ProctorSession
from hirevion_core.proctoring.catalogue import EVIDENCE_KINDS, RANK
from hirevion_core.storage.paths import BlobPath, interview_blob

UPLOAD_TTL = timedelta(minutes=5)
MAX_BYTES = 2 * 1024 * 1024
MAX_SLOTS_PER_SESSION = 500
CONTENT_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
SLOT_KINDS = ("screen", "camera")
# What the contract's evidence `type` means in §67's terms.
TYPE_ALIASES = {"snapshot": "screenshot"}
WINDOW_BEFORE = timedelta(seconds=10)
WINDOW_AFTER = timedelta(seconds=10)
_SHA256 = re.compile(r"[0-9a-f]{64}")
PROCESS_FIELDS = (
    "name",
    "pid",
    "path",
    "publisher",
    "signer",
    "sha256",
    "window_title",
    "matched_by",
)


class Uploads(Protocol):
    def upload_url(
        self, organization_id: UUID, path: BlobPath, expires: timedelta = ...
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class UploadSlot:
    blob_path: str
    upload_url: str
    headers: dict[str, str]


async def issue_upload(
    session: AsyncSession,
    proctor: ProctorSession,
    storage: Uploads,
    *,
    kind: str,
    seq: int,
    content_type: str,
    size: int,
    sha256: str,
) -> UploadSlot:
    """A write-only slot for one snapshot. Asking again for an unclaimed slot with the same hash
    gives the same blob a fresh URL, so a retry is safe."""
    extension = CONTENT_TYPES.get(content_type)
    if kind not in SLOT_KINDS or extension is None or seq < 1:
        raise Invalid("invalid-evidence", "That snapshot can't be accepted")
    digest = sha256.lower()
    if not _SHA256.fullmatch(digest):
        raise Invalid("invalid-evidence", "The snapshot's SHA-256 isn't valid", field="sha256")
    if not 0 < size <= MAX_BYTES:
        raise TooLarge("evidence-too-large", "Snapshots are at most 2 MB")
    path = interview_blob(
        proctor.organization_id, proctor.interview_id, "evidence", f"{seq}-{kind}.{extension}"
    )
    existing = await session.scalar(
        select(ProctorEvidence).where(
            ProctorEvidence.proctor_session_id == proctor.id,
            ProctorEvidence.blob_path == str(path),
        )
    )
    if existing is not None:
        if existing.proctor_event_id is not None or existing.sha256 != digest:
            raise Conflict("evidence-locked", "That snapshot slot was already used")
    else:
        used = await session.scalar(
            select(func.count())
            .select_from(ProctorEvidence)
            .where(
                ProctorEvidence.proctor_session_id == proctor.id, ProctorEvidence.origin == "client"
            )
        )
        if (used or 0) >= MAX_SLOTS_PER_SESSION:
            raise TooLarge("evidence-limit", "Too many snapshots for this interview")
        session.add(
            ProctorEvidence(
                organization_id=proctor.organization_id,
                proctor_session_id=proctor.id,
                interview_id=proctor.interview_id,
                kind="screenshot",
                origin="client",
                blob_path=str(path),
                content_type=content_type,
                bytes=size,
                sha256=digest,
                ref={"capture": kind, "seq": seq},
            )
        )
        await session.flush()
    url = storage.upload_url(proctor.organization_id, path, UPLOAD_TTL)
    return UploadSlot(str(path), url, {"x-ms-blob-type": "BlockBlob"})


async def link(
    session: AsyncSession,
    proctor: ProctorSession,
    event: ProctorEvent,
    references: Sequence[Mapping[str, str]],
) -> list[str]:
    """Attaches the snapshots an event names. Returns the references it refused: a blob this
    session was never given a slot for, or one another event already holds."""
    refused: list[str] = []
    for reference in references:
        path = reference["blob_path"]
        row = await session.scalar(
            select(ProctorEvidence).where(
                ProctorEvidence.proctor_session_id == proctor.id,
                ProctorEvidence.blob_path == path,
            )
        )
        if row is None or row.proctor_event_id not in (None, event.id):
            refused.append(path)
            continue
        kind = TYPE_ALIASES.get(reference["type"], reference["type"])
        row.proctor_event_id = event.id
        if kind in EVIDENCE_KINDS and kind != row.kind:
            row.kind = kind
    return refused


def server_references(
    event: ProctorEvent,
    policy: Mapping[str, Any],
    *,
    interview_started_at: datetime | None,
) -> list[ProctorEvidence]:
    """The references the server adds for an event at WARNING or above (not yet saved)."""
    if RANK[event.severity] < RANK["WARNING"]:
        return []
    start = event.started_at - WINDOW_BEFORE
    end = event.started_at + timedelta(milliseconds=event.duration_ms or 0) + WINDOW_AFTER

    def row(kind: str, **fields: Any) -> ProctorEvidence:
        return ProctorEvidence(
            organization_id=event.organization_id,
            proctor_session_id=event.proctor_session_id,
            interview_id=event.interview_id,
            proctor_event_id=event.id,
            kind=kind,
            origin="server",
            **fields,
        )

    rows: list[ProctorEvidence] = []
    if event.event == "BLOCKED_PROCESS_DETECTED":
        metadata = {key: event.details[key] for key in PROCESS_FIELDS if key in event.details}
        if metadata:
            rows.append(row("process_metadata", ref=metadata))
    recording = policy.get("recording") or {}
    if recording.get("screen"):
        rows.append(row("screen_segment", window_start=start, window_end=end))
    if recording.get("camera") and event.source in ("camera", "third_eye", "native", "interview"):
        rows.append(row("camera_segment", window_start=start, window_end=end))
    if event.source == "third_eye":
        rows.append(row("third_eye_segment", window_start=start, window_end=end))
    if interview_started_at is not None:
        offset = int((event.started_at - interview_started_at).total_seconds() * 1000)
        rows.append(
            row(
                "transcript_segment",
                window_start=start,
                window_end=end,
                ref={"from_ms": max(0, offset - 10_000), "to_ms": max(0, offset) + 20_000},
            )
        )
    return rows


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
