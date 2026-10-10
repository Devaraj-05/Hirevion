"""`hv eval-interviews` and `hv eval-rerun` (SP-10, ADR-0031).

`eval-interviews` runs the interview evaluator over the labelled synthetic set and applies the
gate: thresholds, the committed baseline and the prompt lint. By default it uses the mock
profile, whose deterministic grader follows the prompt as written, so it needs no keys and no
database and runs in CI; `--live` sends the same set to the configured vendor. A candidate
prompt (`--prompt-version`, `--prompt-file`) is tried against the baseline of the one in force.

`eval-rerun` repeats an interview's evaluation with the prompt, rubric weights and skill plan it
recorded and reports the difference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from hirevion_core.ai import build_ai
from hirevion_core.ai.openai_compat import OpenAICompatible
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.ai.types import LLMService
from hirevion_core.db.session import create_database
from hirevion_core.evaluation import registry
from hirevion_core.evaluation.compare import Tolerance
from hirevion_core.evaluation.harness import (
    EvalRun,
    GateResult,
    Thresholds,
    baseline_document,
    gate,
    load_baseline,
    run_eval,
)
from hirevion_core.evaluation.offline import MemoryRecorder, offline_llm
from hirevion_core.evaluation.service import rerun_pinned
from hirevion_core.models import Evaluation
from hirevion_core.settings import load_core_settings


class NotUsable(Exception):
    """The command can't run as asked (an unknown prompt name, a mock profile with --live)."""


@dataclass(frozen=True, slots=True)
class GateRun:
    run: EvalRun
    result: GateResult
    profile: str


def baseline_path() -> Path:
    return Path(str(files("hirevion_core.evaluation") / "eval_set" / "baseline.json"))


async def run_gate(
    *,
    live: bool = False,
    prompt_version: str | None = None,
    prompt_file: Path | None = None,
    rubric_version: str | None = None,
    use_baseline: bool = True,
    thresholds: Thresholds | None = None,
) -> GateRun:
    llm: LLMService
    profile: str
    close = None
    if live:
        settings = load_ai_settings()
        if settings.profile == "mock":
            raise NotUsable("HV_AI_PROFILE is mock; choose dev or production for --live")
        recorder = MemoryRecorder(settings)
        compat = OpenAICompatible(
            settings, recorder, "gemini" if settings.profile == "dev" else "openai"
        )
        llm, close, profile = compat, compat.aclose, settings.profile
    else:
        llm, recorder = offline_llm()
        profile = "mock"
    name = prompt_version or registry.ACTIVE_QUESTION_PROMPT
    text_override: str | None = None
    if prompt_file is not None:
        text_override, name = prompt_file.read_text(encoding="utf-8"), prompt_file.stem
    try:
        run = await run_eval(
            llm,
            prompt_version=name,
            prompt_text=text_override,
            rubric_base=rubric_version or registry.ACTIVE_RUBRIC,
            recorder_rows=recorder.rows,
        )
    except registry.UnknownVersion as error:
        raise NotUsable(str(error)) from error
    finally:
        if close is not None:
            await close()
    result = gate(run, thresholds, load_baseline() if use_baseline else None)
    return GateRun(run, result, profile)


def update_baseline(run: EvalRun) -> Path:
    path = baseline_path()
    path.write_text(
        json.dumps(baseline_document(run), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return path


async def rerun(interview_id: UUID, tolerance: Tolerance) -> Evaluation:
    """Repeats the interview's evaluation with its pinned versions, as the system."""
    core = load_core_settings()
    admin, db = create_database(core, "admin"), create_database(core, "app")
    ai = build_ai(load_ai_settings(), db)
    try:
        async with admin.unscoped() as session:
            organization = await session.scalar(
                text("SELECT organization_id FROM interviews WHERE id = :id"), {"id": interview_id}
            )
        if organization is None:
            raise NotUsable(f"No interview {interview_id}")
        return await rerun_pinned(
            db, ai.llm, UUID(str(organization)), interview_id, None, tolerance
        )
    finally:
        await ai.aclose()
        await db.dispose()
        await admin.dispose()
