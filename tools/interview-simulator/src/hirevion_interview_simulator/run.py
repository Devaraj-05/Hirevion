"""One simulated interview in text mode, from the briefing to the end: system check, consent,
start, then the persona answers every question until the interview completes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hirevion_interview_simulator.client import DesktopClient, SimulatorError
from hirevion_interview_simulator.personas import Persona

MAX_TURNS = 80


@dataclass
class Exchange:
    question_id: str
    question_type: str
    question: str
    answer: str
    status_code: int


@dataclass
class SimulationReport:
    persona: str
    interview_id: str
    status: str = "not_started"
    exchanges: list[Exchange] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    """Codes the API answered with when the persona misbehaved on purpose."""
    final_state: dict[str, Any] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.status == "completed"


async def simulate(
    client: DesktopClient, interview_id: str, candidate: Persona, *, max_turns: int = MAX_TURNS
) -> SimulationReport:
    report = SimulationReport(candidate.name, interview_id)
    briefing = await client.briefing(interview_id)
    if briefing["answer_mode"] != "text":
        raise RuntimeError("the simulator answers in text mode: approve `text_answers` first")
    check = await client.system_check(interview_id, briefing["mandatory_checks"])
    consent = await client.consent(interview_id, briefing["notice"])
    started = await client.start(interview_id, check["id"], consent["id"])
    state = started["state"]
    previous: str | None = None
    for _ in range(max_turns):
        if state["status"] != "in_progress":
            break
        question = state.get("question")
        if question is None:
            raise RuntimeError(f"no open question in state {state}")
        if candidate.name == "cheating" and previous is not None and len(report.refusals) < 2:
            # An answer to a question that's no longer open is refused.
            stale = await client.answer(interview_id, previous, "late answer")
            report.refusals.append(f"{stale.status_code} {stale.json().get('code')}")
        text = candidate.answer(question)
        response = await client.answer(interview_id, question["id"], text)
        report.exchanges.append(
            Exchange(question["id"], question["type"], question["text"], text, response.status_code)
        )
        if response.status_code >= 400:
            raise SimulatorError(response)
        previous = question["id"]
        state = response.json()["state"]
    report.status = state["status"]
    report.final_state = state
    return report
