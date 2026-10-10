"""The eval gate blocks a regressed prompt (SP-10 Task 7; exit criterion 3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hirevion_core.evaluation import registry
from hirevion_core.evaluation.harness import (
    HIGHER_IS_BETTER,
    EvalRun,
    GateResult,
    Thresholds,
    baseline_document,
    gate,
    load_baseline,
    load_set,
    metrics_of,
    report_markdown,
    run_eval,
)
from hirevion_core.evaluation.offline import offline_llm

BAD_PROMPT = (Path(__file__).parent / "fixtures" / "bad-prompt.md").read_text(encoding="utf-8")
ACTIVE = registry.load_prompt(registry.ACTIVE_QUESTION_PROMPT)


async def evaluate(prompt: str | None = None, **kwargs: object) -> tuple[EvalRun, GateResult]:
    llm, recorder = offline_llm()
    run = await run_eval(
        llm,
        prompt_text=prompt,
        prompt_version="candidate-v0" if prompt else registry.ACTIVE_QUESTION_PROMPT,
        recorder_rows=recorder.rows,
    )
    return run, gate(run, **kwargs)  # type: ignore[arg-type]


def failed(result: GateResult) -> set[str]:
    return {c["name"] for c in result.checks if not c["ok"]}


def test_the_labelled_set_covers_every_persona_and_label() -> None:
    document = load_set()
    cases = document["cases"]
    assert document["version"] == "interview-eval-set-v1" and len(cases) == 42
    assert {c["persona"] for c in cases} == {"strong", "partial", "weak", "cheating", "adversarial"}
    assert {c["label"] for c in cases} == {
        "strong",
        "partial",
        "weak",
        "generic_paste",
        "ai_text",
        "injection_only",
        "injection_with_answer",
    }
    assert all(c["expect"]["min"] < c["expect"]["max"] for c in cases)
    assert len({c["id"] for c in cases}) == len(cases)


async def test_the_active_prompt_and_rubric_pass_the_gate() -> None:
    run, result = await evaluate()
    assert result.passed, result.failures
    assert run.lint == [] and run.calls == 42 and run.tokens > 0
    assert run.metrics["band_hit_rate"] == 1.0 and run.metrics["evidence_rate"] == 1.0
    assert run.metrics["injection_resistance"] == 1.0
    assert run.metrics["rank_agreement"] > 0.95


async def test_a_deliberately_bad_prompt_is_blocked() -> None:
    run, result = await evaluate(BAD_PROMPT)
    assert not result.passed
    assert set(run.lint) == {"data", "verbatim"}  # the anchors live in the rubric file
    assert failed(result) >= {
        "prompt:data",
        "prompt:verbatim",
        "evidence_rate",
        "injection_resistance",
        "band_hit_rate",
    }
    assert run.metrics["evidence_rate"] == 0.0  # paraphrases are never verified
    # It did what the candidate asked; only the evidence cap (5.0) kept the worst of it down.
    assert run.metrics["injection_resistance"] == 0.5


@pytest.mark.parametrize(
    ("dropped", "metric"),
    [
        (registry.CLAUSE_VERBATIM, "evidence_rate"),
        (registry.CLAUSE_DATA, "injection_resistance"),
        (registry.CLAUSE_ANCHORS, "band_hit_rate"),
    ],
)
async def test_each_clause_the_pipeline_relies_on_is_guarded_by_a_metric(
    dropped: str, metric: str
) -> None:
    """Take one clause out of the real prompt: a metric, not just the lint, catches it."""

    def without(text: str) -> str:
        return re.sub(re.escape(dropped), "REMOVED", " ".join(text.split()), flags=re.IGNORECASE)

    prompt = without(ACTIVE)
    rubric = without(registry.load_rubric(registry.ACTIVE_RUBRIC))
    llm, recorder = offline_llm()
    run = await run_eval(
        llm,
        prompt_text=prompt,
        prompt_version="candidate-v0",
        rubric_text=rubric,
        recorder_rows=recorder.rows,
    )
    result = gate(run)
    assert not result.passed
    assert metric in failed(result), (metric, run.metrics)


async def test_a_change_that_falls_below_the_baseline_is_blocked_even_above_the_thresholds() -> (
    None
):
    run, _ = await evaluate()
    baseline = {name: run.metrics[name] for name in HIGHER_IS_BETTER}
    assert gate(run, baseline=baseline).passed
    # Stricter than the run achieved by more than the regression margin: a regression.
    higher = {**baseline, "rank_agreement": baseline["rank_agreement"] + 0.05}
    result = gate(run, Thresholds(rank_agreement=0.5), baseline=higher)
    assert not result.passed and "rank_agreement:baseline" in failed(result)
    assert "fell from" in result.failures[0]


async def test_latency_is_bounded() -> None:
    run, _ = await evaluate()
    result = gate(run, Thresholds(latency_p95_ms=-1.0))
    assert "latency_p95_ms" in failed(result)


async def test_the_committed_baseline_is_what_the_active_prompt_scores() -> None:
    """A prompt or rubric change must update the baseline in the same change (`hv
    eval-interviews --update-baseline`), after passing the gate."""
    run, result = await evaluate()
    baseline = load_baseline()
    assert baseline is not None, "run `uv run hv eval-interviews --update-baseline`"
    assert baseline == baseline_document(run)["metrics"]
    assert gate(run, baseline=baseline).passed and result.passed


async def test_the_report_names_the_verdict_and_every_check() -> None:
    run, result = await evaluate(BAD_PROMPT)
    text = report_markdown(run, result, "mock")
    assert "**blocked**" in text and "evidence_rate" in text and "candidate-v0" in text
    passing, ok = await evaluate()
    assert "passed" in report_markdown(passing, ok, "mock")


def test_metrics_need_cases() -> None:
    with pytest.raises(ValueError, match="no cases"):
        metrics_of([])
