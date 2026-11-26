"""What the third eye's whole picture says from frame to frame (C7-2; PRD §53 "unusual movement"
and "workspace"). Pictures are reduced to a 64 x 36 grey thumbnail in memory; nothing is kept.

- Unusual movement: the picture changes a lot between two looks (someone walking through, the
  phone handled), well beyond a candidate shifting in their seat.
- The view changed: the still picture no longer matches the one the interview started with (the
  phone was moved or turned away from the desk), or it went flat (the lens covered, the room
  dark). After `REBASE_SECONDS` a new readable view is accepted as the reference, so the episode
  ends and one move is flagged once; a flat picture never becomes the reference.
- `readable`: whether the picture holds enough to judge anything by, so a covered lens isn't
  taken for the candidate leaving.

Normalised cross-correlation compares views, so light getting brighter or dimmer doesn't count.
These are first settings, to be tuned on real rooms (STATUS "Found in testing").
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from hirevion_vision_agent.watch import Kind

Thumb = NDArray[np.float32]

THUMB_SIZE = (64, 36)
# Mean absolute change of grey level (0 to 1) between two looks half a second apart.
MOVEMENT_THRESHOLD = 0.06
STILL_BELOW = 0.03
# Below this correlation with the reference, the phone shows another view.
VIEW_SIMILARITY = 0.5
REBASE_SECONDS = 30.0
# A thumbnail flatter than this (a covered lens, a black frame) can't be compared.
MIN_SPREAD = 0.01


def thumbnail(pixels: NDArray[np.uint8]) -> Thumb:
    small = Image.fromarray(pixels, "RGB").convert("L").resize(THUMB_SIZE, Image.Resampling.BOX)
    return np.asarray(small, dtype=np.float32) / 255.0


def similarity(a: Thumb, b: Thumb) -> float | None:
    """Normalised cross-correlation, -1 to 1; None when either picture is flat."""
    sa, sb = float(a.std()), float(b.std())
    if sa < MIN_SPREAD or sb < MIN_SPREAD:
        return None
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


class Scene:
    REBASE_SECONDS = REBASE_SECONDS

    def __init__(self) -> None:
        self._previous: Thumb | None = None
        self._reference: Thumb | None = None
        self._changed_since: float | None = None
        self.motion = 0.0
        self.match: float | None = None
        self.readable = False

    def update(self, now: float, pixels: NDArray[np.uint8]) -> dict[Kind, bool]:
        small = thumbnail(pixels)
        previous, self._previous = self._previous, small
        self.motion = 0.0 if previous is None else float(np.mean(np.abs(small - previous)))
        self.readable = float(small.std()) >= MIN_SPREAD
        moving = self.motion >= MOVEMENT_THRESHOLD
        if self._reference is None:
            # The first still, comparable picture (two looks alike, not merely the first one,
            # which may be the phone still being propped up) is the view the interview started
            # with.
            if previous is not None and self.motion < STILL_BELOW and self.readable:
                self._reference = small
            self.match = None
            return {"unusual_movement": moving, "view_changed": False}
        self.match = similarity(small, self._reference)
        flat = not self.readable
        changed = flat or (self.match is not None and self.match < VIEW_SIMILARITY and not moving)
        if changed:
            if self._changed_since is None:
                self._changed_since = now
            elif now - self._changed_since >= REBASE_SECONDS and not flat:
                self._reference, self._changed_since, changed = small, None, False
        elif self.match is not None and self.match >= VIEW_SIMILARITY:
            self._changed_since = None
        return {"unusual_movement": moving, "view_changed": changed}
