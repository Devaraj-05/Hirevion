"""LiveKit's signed webhooks, read as the proctoring engine needs them (SP-14): a candidate's
tracks coming and going, the third eye joining and leaving, and a hidden observer's token."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from livekit import api
from pydantic import SecretStr

from hirevion_core.interview_session.media import LiveKitMedia, MediaError, MediaSettings

INTERVIEW = UUID(int=11)
ORGANIZATION = UUID(int=12)
KEY, SECRET = "devkey", "a-development-secret-of-at-least-32-bytes"


@pytest.fixture
def media() -> LiveKitMedia:
    return LiveKitMedia(
        MediaSettings(livekit_api_key=KEY, livekit_api_secret=SecretStr(SECRET))  # type: ignore[call-arg]
    )


def signed(event: str, identity: str, **extra: Any) -> tuple[str, str]:
    body = json.dumps(
        {
            "event": event,
            "room": {
                "name": f"iv-{INTERVIEW}",
                "metadata": json.dumps(
                    {"interview_id": str(INTERVIEW), "organization_id": str(ORGANIZATION)}
                ),
            },
            "participant": {"identity": identity},
            "createdAt": "1790000000",
            **extra,
        }
    )
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    token = api.AccessToken(KEY, SECRET).with_sha256(digest).to_jwt()
    return body, token


@pytest.mark.parametrize(
    ("source", "track"),
    [("CAMERA", "camera"), ("MICROPHONE", "microphone"), ("SCREEN_SHARE", "screen_share")],
)
def test_a_candidates_tracks_are_read(media: LiveKitMedia, source: str, track: str) -> None:
    for event, kind in (
        ("track_unpublished", "track_unpublished"),
        ("track_published", "track_published"),
    ):
        body, token = signed(event, "candidate-x", track={"source": source})
        parsed = media.parse_webhook(body, token)
        assert (parsed.kind, parsed.track) == (kind, track)
        assert parsed.interview_id == INTERVIEW and parsed.organization_id == ORGANIZATION
        assert parsed.at == datetime.fromtimestamp(1790000000, UTC)


def test_other_tracks_and_other_participants_raise_nothing(media: LiveKitMedia) -> None:
    body, token = signed("track_published", "candidate-x", track={"source": "SCREEN_SHARE_AUDIO"})
    assert media.parse_webhook(body, token).kind == "other"
    body, token = signed("track_published", "observer-x", track={"source": "CAMERA"})
    assert media.parse_webhook(body, token).kind == "other"


def test_the_third_eye_joining_and_leaving_is_read(media: LiveKitMedia) -> None:
    joined = media.parse_webhook(*signed("participant_joined", "third-eye-abc"))
    left = media.parse_webhook(*signed("participant_left", "third-eye-abc"))
    assert (joined.kind, left.kind) == ("third_eye_joined", "third_eye_left")


def test_an_unsigned_or_altered_delivery_is_refused(media: LiveKitMedia) -> None:
    body, token = signed("track_unpublished", "candidate-x", track={"source": "CAMERA"})
    with pytest.raises(MediaError):
        media.parse_webhook(body + " ", token)
    with pytest.raises(MediaError):
        media.parse_webhook(body, "not-a-token")


def test_an_observer_token_is_hidden_and_cannot_publish(media: LiveKitMedia) -> None:
    user = UUID(int=99)
    issued = media.observer_token(
        INTERVIEW, user, "Observer", datetime.now(UTC) + timedelta(hours=1)
    )
    assert issued.identity == f"observer-{user}" and issued.room == f"iv-{INTERVIEW}"
    video = jwt.decode(issued.token, SECRET, algorithms=["HS256"])["video"]
    assert (
        video["hidden"] is True and video["room"] == f"iv-{INTERVIEW}" and video["roomJoin"] is True
    )
    assert not video.get("canPublish") and not video.get("canPublishData")
    assert video["canSubscribe"] is True and not video.get("roomAdmin")
