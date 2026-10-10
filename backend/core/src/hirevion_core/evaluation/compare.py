"""The difference between an evaluation and its pinned re-run (PRD §79: "auditable and
reproducible").

A hosted model is not bit-for-bit repeatable, so reproducing is judged within a tolerance: each
dimension may move by `dimension` points and a question's or the final score by `overall`. The
report also says when the inputs are not the same (a question whose transcript changed, a question
that appears in only one run) and when the model differs from the pinned one, because then a
difference proves nothing about the prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Tolerance:
    dimension: float = 1.0
    overall: float = 0.5


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What a run concluded about one question."""

    overall: float
    dimensions: Mapping[str, float]
    digest: str


def _diff(a: float, b: float) -> float:
    return round(abs(a - b), 2)


def compare(
    base: Mapping[str, Snapshot],
    rerun: Mapping[str, Snapshot],
    *,
    tolerance: Tolerance,
    base_overall: float | None,
    rerun_overall: float | None,
    base_model: str | None,
    rerun_model: str | None,
) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    inputs_changed: list[str] = []
    max_dimension = max_question = 0.0
    for question_id, before in base.items():
        after = rerun.get(question_id)
        if after is None:
            continue
        if before.digest != after.digest:
            inputs_changed.append(question_id)
        moved = {
            name: {
                "base": before.dimensions[name],
                "rerun": after.dimensions.get(name, 0.0),
                "diff": _diff(before.dimensions[name], after.dimensions.get(name, 0.0)),
            }
            for name in before.dimensions
            if _diff(before.dimensions[name], after.dimensions.get(name, 0.0)) > 0
        }
        worst = max((item["diff"] for item in moved.values()), default=0.0)
        overall_diff = _diff(before.overall, after.overall)
        max_dimension = max(max_dimension, worst)
        max_question = max(max_question, overall_diff)
        questions.append(
            {
                "question_id": question_id,
                "base": before.overall,
                "rerun": after.overall,
                "diff": overall_diff,
                "max_dimension_diff": worst,
                "within_tolerance": worst <= tolerance.dimension
                and overall_diff <= tolerance.overall,
                "dimensions": moved,
            }
        )
    missing = [q for q in base if q not in rerun]
    extra = [q for q in rerun if q not in base]
    if base_overall is None or rerun_overall is None:
        final_diff, final_ok = None, base_overall == rerun_overall
    else:
        final_diff = _diff(base_overall, rerun_overall)
        final_ok = final_diff <= tolerance.overall
    within = (
        not inputs_changed
        and not missing
        and not extra
        and final_ok
        and all(item["within_tolerance"] for item in questions)
    )
    return {
        "within_tolerance": within,
        "tolerance": {"dimension": tolerance.dimension, "overall": tolerance.overall},
        "max_dimension_diff": max_dimension,
        "max_question_diff": max_question,
        "overall": {
            "base": base_overall,
            "rerun": rerun_overall,
            "diff": final_diff,
            "within_tolerance": final_ok,
        },
        "questions": questions,
        "inputs_changed": inputs_changed,
        "missing_questions": missing,
        "extra_questions": extra,
        "model_changed": base_model != rerun_model,
        "models": {"base": base_model, "rerun": rerun_model},
    }
