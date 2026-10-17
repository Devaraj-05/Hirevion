"""Pairing a phone as the third eye, and following it through LiveKit (SP-13;
`docs/api/contracts/third-eye.md`).

- The desktop **issues** a pairing (the interview-session token names the interview and the
  candidate); issuing again revokes the live one and removes its phone from the room.
- The phone **redeems** the token once, within two minutes, and gets a publish-only LiveKit
  token and a device secret; it **rejoins** with the secret after a lock outlives its token.
- Its **status** is what LiveKit's webhooks show: the camera published is `connected` (then
  `reconnected`), unpublished or gone is `disconnected`. Each change goes to the interview's
  stream (`THIRD_EYE_STATUS`) and to the proctoring engine's `third_eye` channel, which raises
  `THIRD_EYE_DISCONNECTED` after its debounce (SP-14). Only the current pairing counts: a
  revoked phone that shows up is removed again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Conflict, Gone, NotFound
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.interview_session import realtime
from hirevion_core.interview_session.briefing import third_eye_mode
from hirevion_core.interview_session.conductor import MediaUnavailable
from hirevion_core.interview_session.media import (
    MediaControl,
    MediaError,
    MediaEvent,
    ParticipantToken,
    pairing_of,
    third_eye_identity,
)
from hirevion_core.interviews.lifecycle import By, record_event
from hirevion_core.models import Interview, Job, Organization, ThirdEyePairing
from hirevion_core.third_eye import egress
from hirevion_core.third_eye.egress import EgressRecorder
from hirevion_core.third_eye.pairing import (
    LIVEKIT_TTL,
    PAIRING_TTL,
    USER_AGENT_MAX,
    hash_secret,
    new_secret,
    platform_of,
    public_status,
    qr_url,
)
from hirevion_core.third_eye.settings import ThirdEyeSettings

log = logging.getLogger(__name__)

OPEN_STATUSES = ("invited", "in_progress", "interrupted")
PLACEMENT: dict[str, Any] = {
    "distance_m": 1.5,
    "angle": "side-rear",
    "show": ["face", "hands", "desk", "screen"],
}
THIRD_EYE_KINDS = (
    "third_eye_joined",
    "third_eye_left",
    "third_eye_published",
    "third_eye_unpublished",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PairingView:
    pairing_id: UUID
    interview_id: UUID
    status: str
    expires_at: datetime
    device: dict[str, Any] | None
    connected_at: datetime | None
    last_seen_at: datetime | None
    video: dict[str, Any] | None
    reconnects: int


def view(row: ThirdEyePairing, now: datetime) -> PairingView:
    platform = (row.device or {}).get("platform")
    return PairingView(
        pairing_id=row.id,
        interview_id=row.interview_id,
        status=public_status(row.status, row.expires_at, now),
        expires_at=row.expires_at,
        device={"platform": platform} if platform else None,
        connected_at=row.connected_at,
        last_seen_at=row.last_seen_at,
        video=row.video,
        reconnects=row.reconnects,
    )


@dataclass(frozen=True, slots=True)
class Issued:
    pairing: PairingView
    qr_url: str


@dataclass(frozen=True, slots=True)
class Joined:
    """What the phone needs to stream."""

    pairing_id: UUID
    livekit_url: str | None
    participant: ParticipantToken
    device_token: str | None
    company: str
    job_title: str
    placement: dict[str, Any] = field(default_factory=lambda: dict(PLACEMENT))


Change = Literal["connected", "reconnected", "disconnected", "revoked", "redeemed"]


async def paired(session: AsyncSession, interview: Interview) -> bool:
    """Whether the interview's current pairing has its camera live (what `start` needs when the
    third eye is required)."""
    found = await session.scalar(
        select(ThirdEyePairing.id).where(
            ThirdEyePairing.interview_id == interview.id,
            ThirdEyePairing.revoked_at.is_(None),
            ThirdEyePairing.status == "connected",
        )
    )
    return found is not None


async def current(session: AsyncSession, interview_id: UUID) -> ThirdEyePairing | None:
    found: ThirdEyePairing | None = await session.scalar(
        select(ThirdEyePairing).where(
            ThirdEyePairing.interview_id == interview_id, ThirdEyePairing.revoked_at.is_(None)
        )
    )
    return found


def _revoke(row: ThirdEyePairing, reason: str, now: datetime) -> bool:
    """Revokes `row`; True if its phone was in the room (so it must be removed)."""
    joined = row.redeemed_at is not None
    row.status, row.revoked_at, row.revoke_reason = "revoked", now, reason
    row.device_hash = None
    return joined


class ThirdEye:
    def __init__(
        self,
        db: Database,
        redis: Redis,
        media: MediaControl | None,
        settings: ThirdEyeSettings,
        *,
        recorder: EgressRecorder | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._db = db
        self._redis = redis
        self._media = media
        self._settings = settings
        self._recorder = recorder
        self._clock = clock

    def _require_media(self) -> MediaControl:
        if self._media is None:
            raise MediaUnavailable()
        return self._media

    # The desktop.

    async def issue(
        self, organization_id: UUID, interview_id: UUID, *, account_id: UUID, by: By
    ) -> Issued:
        self._require_media()
        now = self._clock()
        token = new_secret()
        async with self._db.tenant(organization_id) as session:
            interview = await session.get(Interview, interview_id, with_for_update=True)
            if interview is None:
                raise NotFound("interview-not-found", "No such interview")
            if third_eye_mode(interview.policy or {}) == "off":
                raise Conflict("third-eye-off", "This interview doesn't use a phone camera")
            if interview.status not in OPEN_STATUSES:
                raise Conflict("interview-not-open", f"The interview is {interview.status}")
            replaced = await current(session, interview_id)
            kick: list[tuple[UUID, bool]] = []
            if replaced is not None:
                was_connected = replaced.status == "connected"
                if _revoke(replaced, "replaced", now):
                    kick.append((replaced.id, was_connected))
                await session.flush()
            row = ThirdEyePairing(
                id=uuid7(),
                organization_id=organization_id,
                interview_id=interview_id,
                candidate_id=interview.candidate_id,
                account_id=account_id,
                token_hash=hash_secret(token),
                expires_at=now + PAIRING_TTL,
            )
            session.add(row)
            await record_event(
                session,
                interview,
                "third_eye_paired",
                by,
                from_status=interview.status,
                details={
                    "pairing_id": str(row.id),
                    **({"replaced": str(replaced.id)} if replaced is not None else {}),
                },
            )
            await session.flush()
            issued = Issued(view(row, now), qr_url(self._settings.third_eye_url, token))
        for pairing_id, was_connected in kick:
            await self._after_revoke(organization_id, interview_id, pairing_id, was_connected, now)
        return issued

    async def status(
        self, organization_id: UUID, interview_id: UUID, pairing_id: UUID
    ) -> PairingView:
        async with self._db.tenant(organization_id) as session:
            row = await session.get(ThirdEyePairing, pairing_id)
            if row is None or row.interview_id != interview_id:
                raise NotFound("pairing-not-found", "No such pairing")
            return view(row, self._clock())

    async def revoke(
        self, organization_id: UUID, interview_id: UUID, pairing_id: UUID, *, by: By
    ) -> None:
        now = self._clock()
        async with self._db.tenant(organization_id) as session:
            row = await session.get(ThirdEyePairing, pairing_id, with_for_update=True)
            if row is None or row.interview_id != interview_id:
                raise NotFound("pairing-not-found", "No such pairing")
            if row.revoked_at is not None:
                return
            was_connected = row.status == "connected"
            joined = _revoke(row, "revoked", now)
            interview = await session.get_one(Interview, interview_id)
            await record_event(
                session,
                interview,
                "third_eye_revoked",
                by,
                from_status=interview.status,
                details={"pairing_id": str(pairing_id)},
            )
        if joined:
            await self._after_revoke(organization_id, interview_id, pairing_id, was_connected, now)
        else:
            await self._publish(interview_id, pairing_id, "revoked", None, now)

    async def _after_revoke(
        self,
        organization_id: UUID,
        interview_id: UUID,
        pairing_id: UUID,
        was_connected: bool,
        now: datetime,
    ) -> None:
        """Removes a revoked phone from the room; if its camera was live, the third eye is down
        until another phone publishes."""
        await self._kick(interview_id, pairing_id)
        if was_connected:
            await self._vote(organization_id, interview_id, "down", now)
        await self._publish(interview_id, pairing_id, "revoked", None, now)

    async def _kick(self, interview_id: UUID, pairing_id: UUID) -> None:
        if self._media is None:
            return
        try:
            await self._media.remove_participant(interview_id, third_eye_identity(pairing_id))
        except MediaError:
            # It may not have joined; a later join is removed when its webhook arrives.
            log.warning("Couldn't remove the revoked third eye %s", pairing_id, exc_info=True)

    # The phone.

    async def _find(self, secret: str, matched: str) -> Any:
        async with self._db.unscoped() as session:
            found = (
                await session.execute(
                    text("SELECT * FROM auth_third_eye_pairing(:hash)"),
                    {"hash": hash_secret(secret)},
                )
            ).first()
        if found is None or found.matched != matched or found.organization_status != "active":
            raise NotFound("pairing-not-found", "This code isn't valid; scan the QR code again")
        return found

    async def redeem(self, token: str, *, user_agent: str, ip: str | None = None) -> Joined:
        """Spends the pairing token (once, within its two minutes)."""
        media = self._require_media()
        found = await self._find(token, "token")
        organization_id, interview_id = found.organization_id, found.interview_id
        try:
            await media.ensure_room(interview_id, organization_id)
        except MediaError as error:
            raise MediaUnavailable() from error
        now = self._clock()
        device = new_secret()
        agent = (user_agent or "")[:USER_AGENT_MAX]
        async with self._db.tenant(organization_id) as session:
            row = await session.get_one(ThirdEyePairing, found.pairing_id, with_for_update=True)
            if row.revoked_at is not None:
                raise Gone("pairing-revoked", "This pairing was cancelled; scan the new QR code")
            if row.redeemed_at is not None:
                raise Gone("token-used", "This QR code was already used; show a new one")
            if now >= row.expires_at:
                raise Gone("token-expired", "This QR code has expired; show a new one")
            interview = await session.get_one(Interview, interview_id)
            if interview.status not in OPEN_STATUSES:
                raise Conflict("interview-not-open", f"The interview is {interview.status}")
            # `last_seen_at` is LiveKit's to set (webhook times order the deliveries).
            row.status, row.redeemed_at = "redeemed", now
            row.device_hash = hash_secret(device)
            row.device = {"platform": platform_of(agent), "user_agent": agent}
            company, job_title = await self._names(session, interview)
            await record_event(
                session,
                interview,
                "third_eye_redeemed",
                By("candidate", str(row.account_id) if row.account_id else None, ip, agent),
                from_status=interview.status,
                details={"pairing_id": str(row.id), "platform": row.device["platform"]},
            )
            platform = row.device["platform"]
        participant = media.third_eye_token(interview_id, found.pairing_id, now + LIVEKIT_TTL)
        await self._publish(interview_id, found.pairing_id, "redeemed", platform, now)
        return Joined(
            found.pairing_id,
            self._settings.third_eye_livekit_url,
            participant,
            device,
            company,
            job_title,
        )

    async def rejoin(self, device_token: str) -> Joined:
        """A fresh LiveKit token for a phone that already redeemed (after a long lock)."""
        media = self._require_media()
        found = await self._find(device_token, "device")
        now = self._clock()
        async with self._db.tenant(found.organization_id) as session:
            row = await session.get_one(ThirdEyePairing, found.pairing_id, with_for_update=True)
            if row.revoked_at is not None:
                raise Gone("pairing-revoked", "This pairing was cancelled; scan the new QR code")
            interview = await session.get_one(Interview, found.interview_id)
            if interview.status not in OPEN_STATUSES:
                raise Gone("pairing-revoked", f"The interview is {interview.status}")
            company, job_title = await self._names(session, interview)
        participant = media.third_eye_token(found.interview_id, row.id, now + LIVEKIT_TTL)
        return Joined(
            row.id, self._settings.third_eye_livekit_url, participant, None, company, job_title
        )

    @staticmethod
    async def _names(session: AsyncSession, interview: Interview) -> tuple[str, str]:
        company = await session.scalar(
            select(Organization.name).where(Organization.id == interview.organization_id)
        )
        title = await session.scalar(select(Job.title).where(Job.id == interview.job_id))
        return company or "", title or ""

    # LiveKit's webhooks.

    async def on_media(self, event: MediaEvent) -> None:
        """The room's events that concern the third eye and Egress."""
        if event.interview_id is None or event.organization_id is None:
            return
        if event.kind in THIRD_EYE_KINDS:
            await self._observe(event)
        elif event.kind == "egress_ended" and event.egress is not None:
            await egress.egress_ended(
                self._db, event.organization_id, event.interview_id, event.egress, self._clock()
            )
        elif event.kind == "candidate_joined" and self._recorder is not None:
            await self._recorder.start_audio(event.organization_id, event.interview_id, event.at)

    async def _observe(self, event: MediaEvent) -> None:
        pairing_id = pairing_of(event.identity)
        if pairing_id is None or event.interview_id is None or event.organization_id is None:
            return
        change: Change | None = None
        kick = False
        platform: str | None = None
        async with self._db.tenant(event.organization_id) as session:
            row = await session.get(ThirdEyePairing, pairing_id, with_for_update=True)
            if row is None or row.interview_id != event.interview_id:
                return
            if row.revoked_at is not None:
                kick = event.kind in ("third_eye_joined", "third_eye_published")
            elif row.last_seen_at is not None and event.at < row.last_seen_at:
                # A delivery older than what the pairing already shows (out of order).
                return
            else:
                row.last_seen_at = event.at
                platform = (row.device or {}).get("platform")
                if event.kind == "third_eye_published" and row.status != "connected":
                    change = "reconnected" if row.status == "disconnected" else "connected"
                    if change == "reconnected":
                        row.reconnects += 1
                    row.status = "connected"
                    row.connected_at = row.connected_at or event.at
                    if event.width and event.height:
                        row.video = {"width": event.width, "height": event.height, "fps": 15}
                elif (
                    event.kind in ("third_eye_unpublished", "third_eye_left")
                    and row.status == "connected"
                ):
                    change = "disconnected"
                    row.status, row.disconnected_at = "disconnected", event.at
        if kick:
            await self._kick(event.interview_id, pairing_id)
            return
        if change is None:
            return
        await self._publish(event.interview_id, pairing_id, change, platform, event.at)
        await self._vote(
            event.organization_id,
            event.interview_id,
            "down" if change == "disconnected" else "up",
            event.at,
        )
        if event.kind == "third_eye_published" and event.track_sid and self._recorder is not None:
            await self._recorder.start_third_eye(
                event.organization_id, event.interview_id, event.track_sid, event.at
            )

    async def _vote(
        self,
        organization_id: UUID,
        interview_id: UUID,
        state: Literal["up", "down"],
        at: datetime,
    ) -> None:
        """What the server saw, for the proctoring engine's `third_eye` channel (SP-14)."""
        from hirevion_core.proctoring.service import ProctorEngine

        await ProctorEngine(self._db, self._redis).observe(
            organization_id, interview_id, "third_eye", "livekit", state, at
        )

    async def _publish(
        self,
        interview_id: UUID,
        pairing_id: UUID,
        status: Change,
        platform: str | None,
        at: datetime,
    ) -> None:
        """`THIRD_EYE_STATUS` on the interview's stream (the recruiter's dashboard, PRD §91);
        best effort, the pairing row holds the fact."""
        data: dict[str, Any] = {"pairing_id": str(pairing_id), "status": status}
        if platform:
            data["platform"] = platform
        try:
            await realtime.publish(self._redis, interview_id, "THIRD_EYE_STATUS", data, at=at)
        except Exception:
            log.warning("Publishing THIRD_EYE_STATUS failed", exc_info=True)
