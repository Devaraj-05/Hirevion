"""What the third eye's whole picture says, frame to frame (C7-2; PRD §53 "unusual movement" and
"workspace"): sustained large motion, and a view that no longer matches the one the interview
started with (the phone moved or turned away). Synthetic pictures, never photos."""

from __future__ import annotations

import numpy as np

from hirevion_vision_agent.scene import Scene, similarity, thumbnail


def room(seed: int) -> np.ndarray:
    """A room of 40-pixel blocks of different greys: structure like walls, a desk, shelves."""
    coarse = np.random.default_rng(seed).random((9, 16)) * 255
    picture = np.kron(coarse, np.ones((40, 40)))
    return np.repeat(picture[:, :, None], 3, axis=2).astype(np.uint8)


ROOM = room(7)
OTHER_ROOM = room(8)


def with_person_at(x: int, width: int = 60, picture: np.ndarray = ROOM) -> np.ndarray:
    shown = picture.copy()
    shown[120:300, x : x + width] = 40
    return shown


def test_the_same_room_is_similar_and_another_is_not() -> None:
    assert similarity(thumbnail(ROOM), thumbnail(ROOM)) > 0.99
    assert similarity(thumbnail(ROOM), thumbnail(with_person_at(300))) > 0.7
    assert similarity(thumbnail(ROOM), thumbnail(OTHER_ROOM)) < 0.3


def test_a_flat_picture_tells_nothing() -> None:
    flat = np.full((360, 640, 3), 128, dtype=np.uint8)
    assert similarity(thumbnail(flat), thumbnail(ROOM)) is None


def test_a_covered_lens_is_a_changed_view_and_not_readable() -> None:
    scene = Scene()
    for t in range(3):
        scene.update(t * 0.5, ROOM)
    assert scene.readable
    dark = np.zeros((360, 640, 3), dtype=np.uint8)
    flags = [scene.update(5 + t * 0.5, dark) for t in range(4)]
    assert not scene.readable
    assert all(f["view_changed"] for f in flags[1:])
    # A flat picture never becomes the reference, however long it lasts.
    later = scene.update(5 + Scene.REBASE_SECONDS + 5, dark)
    assert later["view_changed"]


def test_a_candidate_shifting_a_little_is_not_unusual_movement() -> None:
    scene = Scene()
    flags = [scene.update(t * 0.5, with_person_at(300 + (t % 2) * 4)) for t in range(20)]
    assert not any(f["unusual_movement"] for f in flags)
    assert not any(f["view_changed"] for f in flags)


def test_large_motion_is_flagged_while_it_lasts() -> None:
    scene = Scene()
    scene.update(0.0, with_person_at(440, width=200))
    # Someone walking through: a figure a third of the picture wide, moving fast.
    moving = [
        scene.update(0.5 + t * 0.5, with_person_at(t * 200 % 440, width=200)) for t in range(6)
    ]
    assert all(f["unusual_movement"] for f in moving)


def test_a_moved_phone_shows_a_changed_view_until_the_new_view_settles() -> None:
    scene = Scene()
    for t in range(4):
        scene.update(t * 0.5, ROOM)
    changed = [scene.update(10 + t * 0.5, OTHER_ROOM) for t in range(10)]
    # The first frame of the new view is motion; once still, the view has changed.
    assert all(f["view_changed"] for f in changed[1:])
    # Still that way after REBASE_SECONDS: the new view becomes the reference.
    later = [scene.update(10 + Scene.REBASE_SECONDS + t * 0.5, OTHER_ROOM) for t in range(4)]
    assert not later[-1]["view_changed"]
