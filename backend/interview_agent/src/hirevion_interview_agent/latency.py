"""Per-turn voice latency: end of the candidate's speech to the AI's first audio.

A turn's total is the end-of-utterance delay plus the LLM's time to first token plus
the TTS time to first byte, the three stages LiveKit Agents reports per `speech_id`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Stage = Literal["eou", "llm_ttft", "tts_ttfb"]
STAGES: tuple[Stage, ...] = ("eou", "llm_ttft", "tts_ttfb")


@dataclass
class TurnLatency:
    speech_id: str
    eou: float | None = None
    llm_ttft: float | None = None
    tts_ttfb: float | None = None

    @property
    def complete(self) -> bool:
        return all(getattr(self, stage) is not None for stage in STAGES)

    @property
    def total(self) -> float:
        return sum(getattr(self, stage) or 0.0 for stage in STAGES)


class LatencyCollector:
    def __init__(self) -> None:
        self._turns: dict[str, TurnLatency] = {}

    def record(self, speech_id: str, stage: Stage, seconds: float) -> None:
        """Keep the first value per stage; later ones are follow-on segments of the same reply."""
        turn = self._turns.setdefault(speech_id, TurnLatency(speech_id))
        if getattr(turn, stage) is None:
            setattr(turn, stage, seconds)

    def completed(self) -> list[TurnLatency]:
        return [turn for turn in self._turns.values() if turn.complete]


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear interpolation between the closest ranks (NumPy's default method)."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(turns: Sequence[TurnLatency]) -> dict[str, dict[str, float]]:
    columns: dict[str, list[float]] = {stage: [] for stage in STAGES}
    columns["total"] = []
    for turn in turns:
        for stage in STAGES:
            columns[stage].append(getattr(turn, stage) or 0.0)
        columns["total"].append(turn.total)
    return {
        name: {"p50": percentile(values, 50), "p95": percentile(values, 95), "max": max(values)}
        for name, values in columns.items()
        if values
    }
