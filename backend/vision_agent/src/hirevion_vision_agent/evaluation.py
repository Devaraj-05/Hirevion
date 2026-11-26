"""The third eye's signals scored on a labelled set (C7-2; master plan SP-15b's exit criterion).

Each session is a timeline of looks (2 a second) with labelled intervals where the condition
held. The detector's errors are modelled per signal: a sighting missed in a frame (`miss`), and
false sightings that start at random (`false_rate` per frame) and last a short burst. The watch
(`watch.Watch`) turns the noisy looks into episodes, which are matched to the labels:

- precision: episodes that overlap a label (1 s either side) over all episodes, as the
  desktop's harness scores them: an episode a false sighting started a moment early is still
  the labelled one;
- recall: labels long enough to report (the hold plus a second) that got an episode;
- false positives per 45 minutes: episodes in 45-minute sessions where nothing happens.

The error rates are assumptions a little worse than the C7-1 run on a laptop's webcam, not
measurements of the detector on real rooms: those need the owner's labelled recordings. Run
`uv run python -m hirevion_vision_agent.evaluation` for the table in ADR-0054.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from hirevion_vision_agent.watch import HOLD_SECONDS, KINDS, Ended, Kind, Watch

TARGET = 0.9
# The budget (ADR-0054): a recruiter reviews at most about one false episode per signal, and two
# in all, in a 45-minute interview.
FP_BUDGET_PER_45_MIN = 1.0
FP_BUDGET_ALL_PER_45_MIN = 2.0
LOOK_SECONDS = 0.5
SESSION_SECONDS = 600.0
CLEAN_SECONDS = 45 * 60.0
# Labels in a session are this far apart: more than the one-a-minute cooldown and the clearing.
SPACING_SECONDS = 80.0
SLACK_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class Noise:
    miss: float
    false_rate: float
    burst: int
    """A false sighting lasts 1 to this many looks."""


NOISE: dict[Kind, Noise] = {
    "phone": Noise(miss=0.15, false_rate=0.01, burst=3),
    "unexpected_person": Noise(miss=0.12, false_rate=0.01, burst=3),
    "secondary_screen": Noise(miss=0.1, false_rate=0.01, burst=4),
    "left_view": Noise(miss=0.05, false_rate=0.01, burst=3),
    "hands_out_of_view": Noise(miss=0.15, false_rate=0.02, burst=6),
    "unusual_movement": Noise(miss=0.1, false_rate=0.01, burst=4),
    "view_changed": Noise(miss=0.05, false_rate=0.005, burst=3),
}


@dataclass(frozen=True, slots=True)
class Label:
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class Score:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    fp_per_45_min: float


Span = tuple[float, float]


def match(labels: Sequence[Label], spans: Sequence[Span], *, hold: float) -> tuple[int, int, int]:
    """(true positives, false positives, missed labels): an episode is true when it overlaps a
    label not yet matched; a label shorter than the hold plus a second isn't expected."""
    matched: set[int] = set()
    tp = fp = 0
    for start, end in spans:
        for index, label in enumerate(labels):
            if index in matched:
                continue
            if start <= label.end + SLACK_SECONDS and end >= label.start - SLACK_SECONDS:
                matched.add(index)
                tp += 1
                break
        else:
            fp += 1
    expected = [i for i, label in enumerate(labels) if label.end - label.start >= hold + 1.0]
    fn = sum(1 for i in expected if i not in matched)
    return tp, fp, fn


def _looks(
    kind: Kind, labels: Sequence[Label], seconds: float, rng: np.random.Generator
) -> list[tuple[float, dict[Kind, bool]]]:
    noise = NOISE[kind]
    looks: list[tuple[float, dict[Kind, bool]]] = []
    burst = 0
    for step in range(int(seconds / LOOK_SECONDS)):
        at = step * LOOK_SECONDS
        truth = any(label.start <= at <= label.end for label in labels)
        if truth:
            shown = bool(rng.random() >= noise.miss)
        elif burst > 0:
            shown, burst = True, burst - 1
        elif rng.random() < noise.false_rate:
            shown, burst = True, int(rng.integers(0, noise.burst))
        else:
            shown = False
        looks.append((at, {kind: shown}))
    return looks


def _episodes(looks: Sequence[tuple[float, dict[Kind, bool]]], kind: Kind) -> list[Span]:
    watch = Watch()
    if kind == "left_view":
        watch.update(-LOOK_SECONDS, {"left_view": False})  # the candidate sat down first
    spans: list[Span] = []
    for at, flags in looks:
        for change in watch.update(at, flags):
            if isinstance(change, Ended) and change.kind == kind:
                spans.append((change.started_at, change.at))
    spans += [(e.started_at, e.at) for e in watch.close_all() if e.kind == kind]
    return spans


def _labels(kind: Kind, rng: np.random.Generator) -> list[Label]:
    hold = HOLD_SECONDS[kind]
    labels: list[Label] = []
    at = 20.0
    while True:
        length = float(rng.uniform(hold + 1.0, hold + 40.0))
        if at + length > SESSION_SECONDS - 10:
            return labels
        labels.append(Label(at, at + length))
        at += length + SPACING_SECONDS + float(rng.uniform(0, 30))


def evaluate(seed: int = 2026, sessions: int = 30, clean: int = 10) -> dict[Kind, Score]:
    rng = np.random.default_rng(seed)
    report: dict[Kind, Score] = {}
    for kind in KINDS:
        tp = fp = fn = 0
        for _ in range(sessions):
            labels = _labels(kind, rng)
            spans = _episodes(_looks(kind, labels, SESSION_SECONDS, rng), kind)
            got = match(labels, spans, hold=HOLD_SECONDS[kind])
            tp, fp, fn = tp + got[0], fp + got[1], fn + got[2]
        false_alarms = sum(
            len(_episodes(_looks(kind, [], CLEAN_SECONDS, rng), kind)) for _ in range(clean)
        )
        report[kind] = Score(
            tp,
            fp,
            fn,
            precision=tp / (tp + fp) if tp + fp else 1.0,
            recall=tp / (tp + fn) if tp + fn else 1.0,
            fp_per_45_min=false_alarms / clean,
        )
    return report


def main() -> None:
    print("| Signal | Precision | Recall | False positives per 45 min |")
    print("|---|---|---|---|")
    for kind, score in evaluate().items():
        print(
            f"| {kind} | {score.precision:.3f} | {score.recall:.3f} | {score.fp_per_45_min:.1f} |"
        )


if __name__ == "__main__":
    main()
