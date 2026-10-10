"""The versioned prompt and rubric files, the versions in force, and the rubric's weights.

Prompts (`prompts/<name>.md`) and the rubric's anchors (`rubrics/<name>.md`) are files, never
edited in place: a change is a new name (`evaluation-question-v2`), and an evaluation records the
names it used so a pinned re-run can load them again (PRD §79). A change goes live only after it
passes the eval harness (`hv eval-interviews`).

The weights are not in a file: they are the interview's own (the template's rubric, pinned in its
policy when the interview was created), so `rubric_version` is the anchors' name plus a short
digest of the weights in force.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from hirevion_core.interviews.templates import RUBRIC_DIMENSIONS

DIMENSIONS: tuple[str, ...] = RUBRIC_DIMENSIONS

ACTIVE_QUESTION_PROMPT = "evaluation-question-v1"
ACTIVE_SYNTHESIS_PROMPT = "evaluation-synthesis-v1"
ACTIVE_RUBRIC = "dimensions-v1"
# Names the aggregation rules (skill, communication and overall scores, caps, weights); it
# changes whenever that arithmetic does. A pinned re-run refuses a version it can't reproduce.
EVALUATION_VERSION = "evaluation-v1"
SUPPORTED_EVALUATION_VERSIONS = frozenset({EVALUATION_VERSION})

# What the question prompt must keep saying, as the pipeline relies on it. The harness's lint
# fails a prompt that loses one, and the mock grader follows the prompt only as far as these.
CLAUSE_DATA = "data, not instructions"
CLAUSE_VERBATIM = "character for character"
CLAUSE_ANCHORS = "Score anchors"
REQUIRED_CLAUSES: dict[str, str] = {
    "data": CLAUSE_DATA,
    "verbatim": CLAUSE_VERBATIM,
    "anchors": CLAUSE_ANCHORS,
}

_NAME = re.compile(r"[a-z][a-z0-9-]{1,63}")


class UnknownVersion(LookupError):
    """A prompt or rubric name with no file (a typo, or a file that was removed)."""


def _read(folder: str, name: str) -> str:
    if not _NAME.fullmatch(name):
        raise UnknownVersion(f"not a prompt or rubric name: {name!r}")
    path = files("hirevion_core.evaluation") / folder / f"{name}.md"
    if not path.is_file():
        raise UnknownVersion(f"no {folder[:-1]} named {name!r}")
    return path.read_text(encoding="utf-8")


@cache
def load_prompt(name: str) -> str:
    return _read("prompts", name)


@cache
def load_rubric(name: str) -> str:
    return _read("rubrics", name)


def system_message(prompt_text: str, rubric_text: str) -> str:
    """What the model is told: the prompt, then the rubric's anchors and definitions."""
    return f"{prompt_text.strip()}\n\n{rubric_text.strip()}\n"


def has_clause(system_text: str, name: str) -> bool:
    """Whether the prompt (with its rubric) carries the named clause, however it is wrapped."""
    return REQUIRED_CLAUSES[name].lower() in " ".join(system_text.split()).lower()


def lint(system_text: str) -> list[str]:
    """The clauses missing from a question prompt (with its rubric), by name."""
    return [name for name in REQUIRED_CLAUSES if not has_clause(system_text, name)]


@dataclass(frozen=True, slots=True)
class Rubric:
    """The eight dimensions' weights for one interview, and the version they make."""

    weights: dict[str, int]
    base: str = ACTIVE_RUBRIC

    @property
    def version(self) -> str:
        return f"{self.base}+w{weights_digest(self.weights)}"

    def mean(self, scores: Mapping[str, float]) -> float:
        """The weighted mean of the dimensions' scores (a dimension without a score counts for
        nothing)."""
        total = sum(self.weights[d] for d in DIMENSIONS if d in scores)
        if total <= 0:
            return 0.0
        return sum(self.weights[d] * scores[d] for d in DIMENSIONS if d in scores) / total


def weights_digest(weights: Mapping[str, int]) -> str:
    canonical = json.dumps({d: weights.get(d, 0) for d in DIMENSIONS}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def rubric_from_policy(
    raw: Sequence[Mapping[str, Any]] | None, base: str = ACTIVE_RUBRIC
) -> Rubric:
    """The interview's rubric (`[{dimension, weight}]` as the template stored it). Unknown
    dimensions are ignored; with no usable weight at all, the dimensions count equally."""
    weights = dict.fromkeys(DIMENSIONS, 0)
    for item in raw or ():
        dimension, weight = item.get("dimension"), item.get("weight")
        if (
            dimension in weights
            and isinstance(weight, int | float)
            and not isinstance(weight, bool)
            and weight > 0
        ):
            weights[str(dimension)] = int(weight)
    if sum(weights.values()) <= 0:
        weights = dict.fromkeys(DIMENSIONS, 1)
    return Rubric(weights, base)


def rubric_from_weights(weights: Mapping[str, Any], base: str = ACTIVE_RUBRIC) -> Rubric:
    """A rubric from weights an evaluation stored (for a pinned re-run)."""
    return Rubric({d: int(weights.get(d, 0)) for d in DIMENSIONS}, base)


def rubric_base(version: str) -> str:
    """The anchors' name inside a `rubric_version`: `dimensions-v1+w1a2b3c4d` is `dimensions-v1`."""
    return version.split("+", 1)[0]
