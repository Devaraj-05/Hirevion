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


@dataclass(frozen=True, slots=True)
class ParticipantToken:
    url: str
    room: str
    identity: str
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MediaEvent:
    """A webhook from the media server, reduced to what the interview needs."""

    kind: Literal["candidate_left", "candidate_joined", "agent_left", "room_finished", "other"]
    interview_id: UUID | None
    organization_id: UUID | None
    identity: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MediaError(Exception):
    """The media server refused or couldn't be reached."""


class MediaControl(Protocol):
    @property
    def url(self) -> str: ...

    def participant_token(
        self, interview_id: UUID, candidate_id: UUID, name: str, expires_at: datetime
    ) -> ParticipantToken: ...

    async def ensure_room(self, interview_id: UUID, organization_id: UUID) -> str: ...

    async def dispatch_agent(self, interview_id: UUID, organization_id: UUID) -> str: ...

    async def candidate_present(self, interview_id: UUID, identity: str) -> bool: ...

    def parse_webhook(self, body: str, authorization: str) -> MediaEvent: ...


def _metadata(interview_id: UUID, organization_id: UUID) -> str:
    return json.dumps({"interview_id": str(interview_id), "organization_id": str(organization_id)})


def _ids(metadata: str | None) -> tuple[UUID | None, UUID | None]:
    try:
        data: dict[str, Any] = json.loads(metadata or "{}")
        return UUID(str(data["interview_id"])), UUID(str(data["organization_id"]))
    except (ValueError, KeyError, TypeError):
        return None, None


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
        interview_id, organization_id = _ids(event.room.metadata)
        if interview_id is None or interview_of(event.room.name) != interview_id:
            return MediaEvent("other", None, None)
        identity = event.participant.identity or None
        is_agent = event.participant.kind == ParticipantInfo.Kind.AGENT
        kind: Literal["candidate_left", "candidate_joined", "agent_left", "room_finished", "other"]
        if event.event == "room_finished":
            kind = "room_finished"
        elif event.event == "participant_left" and is_agent:
            kind = "agent_left"
        elif event.event == "participant_left" and identity and identity.startswith("candidate-"):
            kind = "candidate_left"
        elif event.event == "participant_joined" and identity and identity.startswith("candidate-"):
            kind = "candidate_joined"
        else:
            kind = "other"
        at = (
            datetime.fromtimestamp(event.created_at, UTC) if event.created_at else datetime.now(UTC)
        )
        return MediaEvent(kind, interview_id, organization_id, identity, at)


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
        return MediaEvent(
            data["kind"],
            UUID(data["interview_id"]),
            UUID(data["organization_id"]),
            data.get("identity"),
            datetime.fromisoformat(data["at"]) if data.get("at") else datetime.now(UTC),
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
