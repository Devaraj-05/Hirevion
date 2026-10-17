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


# SP-13: the third eye's camera, its token, and Egress.


def test_the_third_eyes_camera_coming_and_going_is_read(media: LiveKitMedia) -> None:
    track = {"sid": "TR_abc", "source": "CAMERA", "width": 1280, "height": 720}
    published = media.parse_webhook(*signed("track_published", "third-eye-abc", track=track))
    gone = media.parse_webhook(*signed("track_unpublished", "third-eye-abc", track=track))
    assert (published.kind, gone.kind) == ("third_eye_published", "third_eye_unpublished")
    assert published.identity == "third-eye-abc" and published.track_sid == "TR_abc"
    assert (published.width, published.height) == (1280, 720)
    # A third eye can only publish a camera; anything else is ignored.
    body, token = signed("track_published", "third-eye-abc", track={"source": "MICROPHONE"})
    assert media.parse_webhook(body, token).kind == "other"


def egress_body(status: str, filename: str, error: str = "") -> dict[str, Any]:
    second = 1_000_000_000
    return {
        "egressInfo": {
            "egressId": "EG_one",
            "roomName": f"iv-{INTERVIEW}",
            "status": status,
            "startedAt": str(1_790_000_000 * second),
            "endedAt": str(1_790_000_090 * second),
            "error": error,
            "fileResults": [
                {
                    "filename": filename,
                    "startedAt": str(1_790_000_001 * second),
                    "endedAt": str(1_790_000_090 * second),
                    "duration": str(89 * second),
                    "size": "123456",
                    "location": filename,
                }
            ],
        }
    }


def signed_egress(event: str, body: dict[str, Any]) -> tuple[str, str]:
    text = json.dumps({"event": event, "createdAt": "1790000090", **body})
    digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
    return text, api.AccessToken(KEY, SECRET).with_sha256(digest).to_jwt()


def test_an_egress_ending_is_read_with_its_file(media: LiveKitMedia) -> None:
    path = f"{ORGANIZATION}/interviews/{INTERVIEW}/third-eye/third-eye-1-full.webm"
    parsed = media.parse_webhook(
        *signed_egress("egress_ended", egress_body("EGRESS_COMPLETE", path))
    )
    assert parsed.kind == "egress_ended"
    assert (parsed.interview_id, parsed.organization_id) == (INTERVIEW, ORGANIZATION)
    report = parsed.egress
    assert report is not None and report.egress_id == "EG_one" and report.status == "complete"
    assert report.filename == path and report.size == 123456 and report.duration_ms == 89_000
    assert report.started_at == datetime.fromtimestamp(1_790_000_001, UTC)


def test_a_failed_egress_and_an_unknown_room_are_read_as_such(media: LiveKitMedia) -> None:
    path = f"{ORGANIZATION}/interviews/{INTERVIEW}/audio/conversation-audio-1-full.mp4"
    failed = media.parse_webhook(
        *signed_egress("egress_ended", egress_body("EGRESS_FAILED", path, error="no space"))
    )
    assert failed.egress is not None and failed.egress.status == "failed"
    assert failed.egress.error == "no space"
    # The organisation comes from the file's path; one that doesn't match the room is ignored.
    elsewhere = f"{ORGANIZATION}/interviews/{UUID(int=5)}/audio/conversation-audio-1-full.mp4"
    ignored = media.parse_webhook(
        *signed_egress("egress_ended", egress_body("EGRESS_COMPLETE", elsewhere))
    )
    assert ignored.kind == "other"


def test_the_third_eyes_token_publishes_a_camera_and_nothing_else(media: LiveKitMedia) -> None:
    pairing = UUID(int=77)
    expires = datetime.now(UTC) + timedelta(minutes=10)
    issued = media.third_eye_token(INTERVIEW, pairing, expires)
    assert issued.identity == f"third-eye-{pairing}" and issued.room == f"iv-{INTERVIEW}"
    claims = jwt.decode(issued.token, SECRET, algorithms=["HS256"])
    video = claims["video"]
    assert video["roomJoin"] is True and video["room"] == f"iv-{INTERVIEW}"
    assert video["canPublish"] is True and video["canPublishSources"] == ["camera"]
    assert video["canSubscribe"] is False and video["canPublishData"] is False
    assert not video.get("roomAdmin") and not video.get("roomRecord")
    assert not video.get("canUpdateOwnMetadata")
    # Short-lived: at most the ten minutes asked for.
    assert claims["exp"] - claims["nbf"] <= 600
