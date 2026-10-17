"""Rooms, participant tokens, agent dispatch and LiveKit's webhooks (SP-09a), behind
`MediaControl` so the cloud move (master plan §5.4) and the tests can swap the implementation.

- **Room:** `iv-{interview_id}`, created with the interview and organisation in its metadata.
- **Candidate token:** identity `candidate-{candidate_id}`. It may join that one room, subscribe,
  publish the microphone, the camera and a screen share, and send data. It may not create,
  administer or record rooms, change its own metadata or publish anything else.
- **Agent:** `hirevion-interviewer`, dispatched explicitly with `{interview_id,
  organization_id}` as the job's metadata; it never auto-joins rooms.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file

log = logging.getLogger(__name__)

AGENT_NAME = "hirevion-interviewer"
CANDIDATE_SOURCES = ("microphone", "camera", "screen_share")
ROOM_PREFIX = "iv-"
MAX_PARTICIPANTS = 6
"""The candidate, the interview agent, the vision agent, the third eye and two observers."""
EMPTY_TIMEOUT_SECONDS = 600


class MediaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HV_", extra="ignore", hide_input_in_errors=True, populate_by_name=True
    )

    livekit_url: str = Field(
        "ws://127.0.0.1:7880", validation_alias=AliasChoices("LIVEKIT_URL", "HV_LIVEKIT_URL")
    )
    """Where the API reaches LiveKit's server API."""
    livekit_public_url: str | None = None
    """What the desktop connects to (`wss://livekit.hirevion.localhost` locally behind Caddy)."""
    livekit_api_key: str = Field(
        "", validation_alias=AliasChoices("LIVEKIT_API_KEY", "HV_LIVEKIT_API_KEY")
    )
    livekit_api_secret: SecretStr = Field(
        SecretStr(""), validation_alias=AliasChoices("LIVEKIT_API_SECRET", "HV_LIVEKIT_API_SECRET")
    )
    agent_name: str = AGENT_NAME
    """`HV_AGENT_NAME`: the name the interview agent registers under (the agent's own setting)."""
    media_backend: Literal["livekit", "fake"] = "livekit"
    """`fake` (CI, the simulator, end-to-end tests) signs no real tokens and dispatches nothing;
    production refuses it."""
    environment: str = "development"

    @property
    def configured(self) -> bool:
        return bool(self.livekit_api_key and self.livekit_api_secret.get_secret_value())

    @property
    def client_url(self) -> str:
        return self.livekit_public_url or self.livekit_url

    @property
    def http_url(self) -> str:
        url = self.livekit_url
        if url.startswith("ws://"):
            return "http://" + url[5:]
        if url.startswith("wss://"):
            return "https://" + url[6:]
        return url


def load_media_settings() -> MediaSettings:
    return MediaSettings(_env_file=repo_env_file())  # type: ignore[call-arg]


def room_name(interview_id: UUID) -> str:
    return f"{ROOM_PREFIX}{interview_id}"


def interview_of(room: str) -> UUID | None:
    if not room.startswith(ROOM_PREFIX):
        return None
    try:
        return UUID(room[len(ROOM_PREFIX) :])
    except ValueError:
        return None


def candidate_identity(candidate_id: UUID) -> str:
    return f"candidate-{candidate_id}"


def observer_identity(user_id: UUID) -> str:
    return f"observer-{user_id}"


@dataclass(frozen=True, slots=True)
class ParticipantToken:
    url: str
    room: str
    identity: str
    token: str
    expires_at: datetime


MediaKind = Literal[
    "candidate_left",
    "candidate_joined",
    "agent_left",
    "room_finished",
    "track_published",
    "track_unpublished",
    "third_eye_joined",
    "third_eye_left",
    "third_eye_published",
    "third_eye_unpublished",
    "egress_ended",
    "other",
]
THIRD_EYE_PREFIX = "third-eye-"
THIRD_EYE_SOURCES = ("camera",)
"""All a third eye may publish (SP-13): its camera; no microphone, screen or data."""
TRACK_NAMES = {1: "camera", 2: "microphone", 3: "screen_share"}
"""LiveKit's `TrackSource` values for what a candidate publishes."""
CAMERA_SOURCE = 1


def third_eye_identity(pairing_id: UUID) -> str:
    return f"{THIRD_EYE_PREFIX}{pairing_id}"


def pairing_of(identity: str | None) -> UUID | None:
    """The pairing a third eye's identity names, or None."""
    if not identity or not identity.startswith(THIRD_EYE_PREFIX):
        return None
    try:
        return UUID(identity[len(THIRD_EYE_PREFIX) :])
    except ValueError:
        return None


EgressStatus = Literal["active", "complete", "failed"]


@dataclass(frozen=True, slots=True)
class EgressReport:
    """What an `egress_ended` webhook says about one recording LiveKit wrote."""

    egress_id: str
    status: EgressStatus
    filename: str
    """The file's path as the request named it (`{org}/interviews/{id}/{folder}/{file}`)."""
    location: str = ""
    size: int = 0
    duration_ms: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str = ""


@dataclass(frozen=True, slots=True)
class EgressTarget:
    """Where LiveKit writes a recording: `filepath` under its output directory (a shared volume
    locally), or straight into the blob container when `azure` is set (the cloud)."""

    filepath: str
    azure: tuple[str, str, str] | None = None
    """(account name, account key, container), for LiveKit's own upload."""


@dataclass(frozen=True, slots=True)
class MediaEvent:
    """A webhook from the media server, reduced to what the interview needs."""

    kind: MediaKind
    interview_id: UUID | None
    organization_id: UUID | None
    identity: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    track: str | None = None
    """For a candidate's track: `camera`, `microphone` or `screen_share`."""
    track_sid: str | None = None
    width: int | None = None
    height: int | None = None
    egress: EgressReport | None = None


class MediaError(Exception):
    """The media server refused or couldn't be reached."""


class MediaControl(Protocol):
    @property
    def url(self) -> str: ...

    def participant_token(
        self, interview_id: UUID, candidate_id: UUID, name: str, expires_at: datetime
    ) -> ParticipantToken: ...

    def observer_token(
        self, interview_id: UUID, user_id: UUID, name: str, expires_at: datetime
    ) -> ParticipantToken: ...

    async def ensure_room(self, interview_id: UUID, organization_id: UUID) -> str: ...

    async def dispatch_agent(self, interview_id: UUID, organization_id: UUID) -> str: ...

    async def candidate_present(self, interview_id: UUID, identity: str) -> bool: ...

    def parse_webhook(self, body: str, authorization: str) -> MediaEvent: ...

    def third_eye_token(
        self, interview_id: UUID, pairing_id: UUID, expires_at: datetime
    ) -> ParticipantToken: ...

    async def remove_participant(self, interview_id: UUID, identity: str) -> None: ...

    async def start_audio_egress(self, interview_id: UUID, target: EgressTarget) -> str: ...

    async def start_track_egress(
        self, interview_id: UUID, track_sid: str, target: EgressTarget
    ) -> str: ...


def _metadata(interview_id: UUID, organization_id: UUID) -> str:
    return json.dumps({"interview_id": str(interview_id), "organization_id": str(organization_id)})


def _ids(metadata: str | None) -> tuple[UUID | None, UUID | None]:
    try:
        data: dict[str, Any] = json.loads(metadata or "{}")
        return UUID(str(data["interview_id"])), UUID(str(data["organization_id"]))
    except (ValueError, KeyError, TypeError):
        return None, None


# LiveKit's `EgressStatus`: complete (3) and limit reached (6) wrote a file; failed (4) and
# aborted (5) didn't.
_EGRESS_STATUSES: dict[int, EgressStatus] = {3: "complete", 6: "complete", 4: "failed", 5: "failed"}
_BLOB_KEY = re.compile(
    r"(?P<org>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/interviews/"
    r"(?P<interview>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/[^/]+/[^/]+$"
)


def _from_ns(value: int) -> datetime | None:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC) if value else None


def egress_key(path: str) -> tuple[UUID, UUID, str] | None:
    """The organisation, interview and blob key (`{org}/interviews/{id}/{folder}/{file}`) in an
    Egress output path, which may start with LiveKit's output directory."""
    found = _BLOB_KEY.search(path)
    if found is None:
        return None
    return UUID(found["org"]), UUID(found["interview"]), path[found.start() :]


def _egress_path(info: Any) -> str:
    """The file an egress writes, from its request (also there when it failed early)."""
    request = info.WhichOneof("request")
    if request == "room_composite":
        outputs = info.room_composite.file_outputs
        if outputs:
            return str(outputs[0].filepath)
    elif request == "track" and info.track.WhichOneof("output") == "file":
        return str(info.track.file.filepath)
    for result in info.file_results:
        return str(result.filename)
    return ""


def _egress_event(info: Any, at: datetime) -> MediaEvent:
    interview_id = interview_of(info.room_name)
    found = egress_key(_egress_path(info))
    if interview_id is None or found is None or found[1] != interview_id:
        return MediaEvent("other", None, None)
    organization_id, _, key = found
    result = info.file_results[0] if info.file_results else None
    report = EgressReport(
        egress_id=str(info.egress_id),
        status=_EGRESS_STATUSES.get(int(info.status), "active"),
        filename=key,
        location=str(result.location) if result is not None else "",
        size=int(result.size) if result is not None else 0,
        duration_ms=int(result.duration) // 1_000_000 if result is not None else 0,
        started_at=_from_ns(int(result.started_at if result is not None else info.started_at)),
        ended_at=_from_ns(int(result.ended_at if result is not None else info.ended_at)),
        error=str(info.error)[:500],
    )
    return MediaEvent("egress_ended", interview_id, organization_id, at=at, egress=report)


class LiveKitMedia:
    def __init__(self, settings: MediaSettings) -> None:
        if not settings.configured:
            raise ValueError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set")
        self._settings = settings

    @property
    def url(self) -> str:
        return self._settings.client_url

    def _secret(self) -> str:
        return self._settings.livekit_api_secret.get_secret_value()

    def participant_token(
        self, interview_id: UUID, candidate_id: UUID, name: str, expires_at: datetime
    ) -> ParticipantToken:
        from livekit import api

        room = room_name(interview_id)
        identity = candidate_identity(candidate_id)
        ttl = max(timedelta(minutes=1), expires_at - datetime.now(UTC))
        grants = api.VideoGrants(
            room_join=True,
            room=room,
            room_create=False,
            room_list=False,
            room_record=False,
            room_admin=False,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
            can_publish_sources=list(CANDIDATE_SOURCES),
            can_update_own_metadata=False,
            hidden=False,
        )
        token = (
            api.AccessToken(self._settings.livekit_api_key, self._secret())
            .with_identity(identity)
            .with_name(name)
            .with_ttl(ttl)
            .with_grants(grants)
            .to_jwt()
        )
        return ParticipantToken(self.url, room, identity, token, expires_at)

    def observer_token(
        self, interview_id: UUID, user_id: UUID, name: str, expires_at: datetime
    ) -> ParticipantToken:
        """A recruiter's way to watch: hidden (no one in the room sees them), subscribe-only."""
        from livekit import api

        room = room_name(interview_id)
        identity = observer_identity(user_id)
        ttl = max(timedelta(minutes=1), expires_at - datetime.now(UTC))
        grants = api.VideoGrants(
            room_join=True,
            room=room,
            room_create=False,
            room_list=False,
            room_record=False,
            room_admin=False,
            can_publish=False,
            can_subscribe=True,
            can_publish_data=False,
            can_update_own_metadata=False,
            hidden=True,
        )
        token = (
            api.AccessToken(self._settings.livekit_api_key, self._secret())
            .with_identity(identity)
            .with_name(name)
            .with_ttl(ttl)
            .with_grants(grants)
            .to_jwt()
        )
        return ParticipantToken(self.url, room, identity, token, expires_at)

    async def ensure_room(self, interview_id: UUID, organization_id: UUID) -> str:
        from livekit import api

        room = room_name(interview_id)
        try:
            async with api.LiveKitAPI(
                self._settings.http_url, self._settings.livekit_api_key, self._secret()
            ) as client:
                await client.room.create_room(
                    api.CreateRoomRequest(
                        name=room,
                        empty_timeout=EMPTY_TIMEOUT_SECONDS,
                        max_participants=MAX_PARTICIPANTS,
                        metadata=_metadata(interview_id, organization_id),
                    )
                )
        except Exception as error:
            raise MediaError(f"couldn't create room {room}") from error
        return room

    async def dispatch_agent(self, interview_id: UUID, organization_id: UUID) -> str:
        from livekit import api

        room = room_name(interview_id)
        try:
            async with api.LiveKitAPI(
                self._settings.http_url, self._settings.livekit_api_key, self._secret()
            ) as client:
                dispatch = await client.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(
                        agent_name=self._settings.agent_name,
                        room=room,
                        metadata=_metadata(interview_id, organization_id),
                    )
                )
        except Exception as error:
            raise MediaError(f"couldn't dispatch the agent to {room}") from error
        return str(dispatch.id)

    async def candidate_present(self, interview_id: UUID, identity: str) -> bool:
        """Whether `identity` is in the room now (a late webhook mustn't interrupt them)."""
        from livekit import api

        try:
            async with api.LiveKitAPI(
                self._settings.http_url, self._settings.livekit_api_key, self._secret()
            ) as client:
                answer = await client.room.list_participants(
                    api.ListParticipantsRequest(room=room_name(interview_id))
                )
        except Exception:
            # Can't tell: trust the event.
            log.warning("Couldn't list the participants of %s", room_name(interview_id))
            return False
        return any(p.identity == identity for p in answer.participants)

    def parse_webhook(self, body: str, authorization: str) -> MediaEvent:
        from livekit import api
        from livekit.protocol.models import ParticipantInfo

        receiver = api.WebhookReceiver(
            api.TokenVerifier(self._settings.livekit_api_key, self._secret())
        )
        try:
            event = receiver.receive(body, authorization)
        except Exception as error:
            raise MediaError("the webhook's signature doesn't match") from error
        at = (
            datetime.fromtimestamp(event.created_at, UTC) if event.created_at else datetime.now(UTC)
        )
        if event.event == "egress_ended":
            # Egress events carry no room metadata: the output path names the organisation.
            return _egress_event(event.egress_info, at)
        interview_id, organization_id = _ids(event.room.metadata)
        if interview_id is None or interview_of(event.room.name) != interview_id:
            return MediaEvent("other", None, None)
        identity = event.participant.identity or None
        is_agent = event.participant.kind == ParticipantInfo.Kind.AGENT
        kind: MediaKind
        track: str | None = None
        if event.event == "room_finished":
            kind = "room_finished"
        elif event.event in ("track_published", "track_unpublished") and (
            identity and identity.startswith(THIRD_EYE_PREFIX)
        ):
            if int(event.track.source) != CAMERA_SOURCE:
                return MediaEvent("other", None, None)
            return MediaEvent(
                "third_eye_published"
                if event.event == "track_published"
                else "third_eye_unpublished",
                interview_id,
                organization_id,
                identity,
                at,
                track_sid=event.track.sid or None,
                width=int(event.track.width) or None,
                height=int(event.track.height) or None,
            )
        elif event.event in ("track_published", "track_unpublished") and (
            identity and identity.startswith("candidate-")
        ):
            track = TRACK_NAMES.get(int(event.track.source))
            if track is None:
                kind = "other"
            else:
                kind = (
                    "track_published" if event.event == "track_published" else "track_unpublished"
                )
        elif event.event in ("participant_joined", "participant_left") and (
            identity and identity.startswith(THIRD_EYE_PREFIX)
        ):
            kind = "third_eye_joined" if event.event == "participant_joined" else "third_eye_left"
        elif event.event == "participant_left" and is_agent:
            kind = "agent_left"
        elif event.event == "participant_left" and identity and identity.startswith("candidate-"):
            kind = "candidate_left"
        elif event.event == "participant_joined" and identity and identity.startswith("candidate-"):
            kind = "candidate_joined"
        else:
            kind = "other"
        return MediaEvent(kind, interview_id, organization_id, identity, at, track)

    def third_eye_token(
        self, interview_id: UUID, pairing_id: UUID, expires_at: datetime
    ) -> ParticipantToken:
        """The phone's token (SP-13): join this one room and publish a camera; nothing else, not
        even subscribing. It lives until `expires_at`; LiveKit refreshes it while connected."""
        from livekit import api

        room = room_name(interview_id)
        identity = third_eye_identity(pairing_id)
        ttl = max(timedelta(seconds=30), expires_at - datetime.now(UTC))
        grants = api.VideoGrants(
            room_join=True,
            room=room,
            room_create=False,
            room_list=False,
            room_record=False,
            room_admin=False,
            can_publish=True,
            can_subscribe=False,
            can_publish_data=False,
            can_publish_sources=list(THIRD_EYE_SOURCES),
            can_update_own_metadata=False,
            hidden=False,
        )
        token = (
            api.AccessToken(self._settings.livekit_api_key, self._secret())
            .with_identity(identity)
            .with_name("Third eye")
            .with_ttl(ttl)
            .with_grants(grants)
            .to_jwt()
        )
        return ParticipantToken(self.url, room, identity, token, expires_at)

    async def remove_participant(self, interview_id: UUID, identity: str) -> None:
        """Disconnects `identity` from the room; one that isn't there is already gone."""
        from livekit import api

        try:
            async with api.LiveKitAPI(
                self._settings.http_url, self._settings.livekit_api_key, self._secret()
            ) as client:
                await client.room.remove_participant(
                    api.RoomParticipantIdentity(room=room_name(interview_id), identity=identity)
                )
        except Exception as error:
            if "not found" in str(error).lower() or "not_found" in str(error).lower():
                return
            raise MediaError(f"couldn't remove {identity}") from error

    async def start_audio_egress(self, interview_id: UUID, target: EgressTarget) -> str:
        """Records the room's mixed audio (the candidate's microphone and the agent's voice)."""
        from livekit import api

        output = api.EncodedFileOutput(file_type=api.EncodedFileType.MP4, filepath=target.filepath)
        if target.azure is not None:
            output.azure.CopyFrom(_azure(target.azure))
        request = api.RoomCompositeEgressRequest(
            room_name=room_name(interview_id), audio_only=True, file_outputs=[output]
        )
        try:
            async with api.LiveKitAPI(
                self._settings.http_url, self._settings.livekit_api_key, self._secret()
            ) as client:
                info = await client.egress.start_room_composite_egress(request)
        except Exception as error:
            raise MediaError(f"couldn't record the audio of {room_name(interview_id)}") from error
        return str(info.egress_id)

    async def start_track_egress(
        self, interview_id: UUID, track_sid: str, target: EgressTarget
    ) -> str:
        """Records one published track as it arrives (no transcoding: VP8 into WebM)."""
        from livekit import api

        output = api.DirectFileOutput(filepath=target.filepath)
        if target.azure is not None:
            output.azure.CopyFrom(_azure(target.azure))
        request = api.TrackEgressRequest(
            room_name=room_name(interview_id), track_id=track_sid, file=output
        )
        try:
            async with api.LiveKitAPI(
                self._settings.http_url, self._settings.livekit_api_key, self._secret()
            ) as client:
                info = await client.egress.start_track_egress(request)
        except Exception as error:
            raise MediaError(f"couldn't record track {track_sid}") from error
        return str(info.egress_id)


def _azure(azure: tuple[str, str, str]) -> Any:
    from livekit import api

    account, key, container = azure
    return api.AzureBlobUpload(account_name=account, account_key=key, container_name=container)


@dataclass
class FakeMedia:
    """What tests and the mock profile use: records rooms and dispatches, signs nothing real."""

    url: str = "wss://livekit.example.test"
    rooms: list[str] = field(default_factory=list)
    dispatches: list[str] = field(default_factory=list)
    tokens: list[ParticipantToken] = field(default_factory=list)
    events: list[MediaEvent] = field(default_factory=list)
    present: set[str] = field(default_factory=set)
    """Identities the fake room holds now."""
    fail: bool = False
    removed: list[str] = field(default_factory=list)
    """Identities `remove_participant` disconnected."""
    egresses: list[tuple[str, str, EgressTarget]] = field(default_factory=list)
    """(egress id, what it records: `audio` or a track sid, where it writes)."""

    def third_eye_token(
        self, interview_id: UUID, pairing_id: UUID, expires_at: datetime
    ) -> ParticipantToken:
        token = ParticipantToken(
            self.url,
            room_name(interview_id),
            third_eye_identity(pairing_id),
            f"fake-third-eye-{pairing_id}",
            expires_at,
        )
        self.tokens.append(token)
        return token

    async def remove_participant(self, interview_id: UUID, identity: str) -> None:
        if self.fail:
            raise MediaError("the fake media server is down")
        self.removed.append(identity)
        self.present.discard(identity)

    async def start_audio_egress(self, interview_id: UUID, target: EgressTarget) -> str:
        if self.fail:
            raise MediaError("the fake media server is down")
        egress_id = f"EG_{len(self.egresses) + 1}"
        self.egresses.append((egress_id, "audio", target))
        return egress_id

    async def start_track_egress(
        self, interview_id: UUID, track_sid: str, target: EgressTarget
    ) -> str:
        if self.fail:
            raise MediaError("the fake media server is down")
        egress_id = f"EG_{len(self.egresses) + 1}"
        self.egresses.append((egress_id, track_sid, target))
        return egress_id

    def participant_token(
        self, interview_id: UUID, candidate_id: UUID, name: str, expires_at: datetime
    ) -> ParticipantToken:
        token = ParticipantToken(
            self.url,
            room_name(interview_id),
            candidate_identity(candidate_id),
            f"fake-token-{interview_id}",
            expires_at,
        )
        self.tokens.append(token)
        return token

    def observer_token(
        self, interview_id: UUID, user_id: UUID, name: str, expires_at: datetime
    ) -> ParticipantToken:
        token = ParticipantToken(
            self.url,
            room_name(interview_id),
            observer_identity(user_id),
            f"fake-observer-{interview_id}",
            expires_at,
        )
        self.tokens.append(token)
        return token

    async def ensure_room(self, interview_id: UUID, organization_id: UUID) -> str:
        if self.fail:
            raise MediaError("the fake media server is down")
        room = room_name(interview_id)
        if room not in self.rooms:
            self.rooms.append(room)
        return room

    async def dispatch_agent(self, interview_id: UUID, organization_id: UUID) -> str:
        if self.fail:
            raise MediaError("the fake media server is down")
        self.dispatches.append(room_name(interview_id))
        return f"AD_{len(self.dispatches)}"

    async def candidate_present(self, interview_id: UUID, identity: str) -> bool:
        return identity in self.present

    def parse_webhook(self, body: str, authorization: str) -> MediaEvent:
        if authorization != "fake-signature":
            raise MediaError("bad signature")
        data = json.loads(body)
        egress = data.get("egress")
        report = None
        if egress is not None:
            report = EgressReport(
                egress_id=egress["egress_id"],
                status=egress.get("status", "complete"),
                filename=egress["filename"],
                location=egress.get("location", ""),
                size=int(egress.get("size", 0)),
                duration_ms=int(egress.get("duration_ms", 0)),
                started_at=datetime.fromisoformat(egress["started_at"])
                if egress.get("started_at")
                else None,
                error=egress.get("error", ""),
            )
        return MediaEvent(
            data["kind"],
            UUID(data["interview_id"]),
            UUID(data["organization_id"]),
            data.get("identity"),
            datetime.fromisoformat(data["at"]) if data.get("at") else datetime.now(UTC),
            data.get("track"),
            track_sid=data.get("track_sid"),
            width=data.get("width"),
            height=data.get("height"),
            egress=report,
        )


def build_media(settings: MediaSettings | None = None) -> MediaControl | None:
    """LiveKit when it is configured, the fake when asked for outside production, else None
    (the interview routes then answer 503)."""
    resolved = settings or load_media_settings()
    if resolved.media_backend == "fake":
        if resolved.environment == "production":
            raise ValueError("HV_MEDIA_BACKEND=fake can't be used in production")
        log.warning("Media is faked: no LiveKit rooms or agents (HV_MEDIA_BACKEND=fake)")
        return FakeMedia()
    if not resolved.configured:
        log.warning("LiveKit isn't configured: voice interviews can't start")
        return None
    return LiveKitMedia(resolved)
