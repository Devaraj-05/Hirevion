"""The vision agent's job (C7-1): which interview the dispatch names, which track it watches, and
when it stops."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from livekit import rtc

from hirevion_vision_agent.agent import is_phone_camera, job_ids, still_running

INTERVIEW, ORG = UUID(int=5), UUID(int=6)


def test_the_dispatch_names_the_interview_and_organisation() -> None:
    metadata = f'{{"interview_id": "{INTERVIEW}", "organization_id": "{ORG}"}}'
    assert job_ids(metadata) == (INTERVIEW, ORG)
    with pytest.raises(KeyError):
        job_ids("{}")


def test_only_the_phones_camera_is_watched() -> None:
    camera = SimpleNamespace(kind=rtc.TrackKind.KIND_VIDEO, source=rtc.TrackSource.SOURCE_CAMERA)
    phone = SimpleNamespace(identity="third-eye-01a1df63-581a-78ea-a9e3-20b0f7fa88a9")
    candidate = SimpleNamespace(identity="candidate-01a1df63-581a-78ea-a9e3-20b0f7fa88a9")
    screen = SimpleNamespace(
        kind=rtc.TrackKind.KIND_VIDEO, source=rtc.TrackSource.SOURCE_SCREENSHARE
    )
    assert is_phone_camera(camera, phone)
    assert not is_phone_camera(camera, candidate)  # the candidate's own camera
    assert not is_phone_camera(screen, phone)


def test_it_watches_while_the_interview_runs_or_is_paused() -> None:
    assert still_running("in_progress") and still_running("interrupted")
    assert not still_running("completed") and not still_running(None)
