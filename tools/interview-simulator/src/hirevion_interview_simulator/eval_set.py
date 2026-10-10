"""The labelled set the evaluation gate runs on (SP-10, ADR-0031): what the simulator's personas
say to a fixed bank of questions, each with the band its overall score should fall in.

The labels come from what the persona is, not from any grader: a candidate who covers every
expected concept belongs in the top band, one who covers about half in the middle, vague one-liners
and generic pastes at the bottom, and a candidate who only tries to instruct the evaluator gets
almost nothing. `hv eval-interviews` runs the evaluator over `cases.json` (generated here by
`write`, and checked against this builder by a test, so the personas can't drift unnoticed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hirevion_interview_simulator.personas import INJECTIONS, persona

VERSION = "interview-eval-set-v1"
BANDS: dict[str, tuple[float, float]] = {
    "strong": (7.5, 10.0),
    "partial": (4.0, 8.0),
    "weak": (0.0, 3.5),
    "generic_paste": (0.0, 4.0),
    "ai_text": (7.5, 10.0),
    "injection_only": (0.0, 2.0),
    "injection_with_answer": (0.0, 6.0),
}
# (skill, difficulty, question, expected concepts)
QUESTIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "PostgreSQL",
        "medium",
        "How do you find out why a query is slow?",
        ("explain analyze", "sequential scan", "statistics"),
    ),
    (
        "PostgreSQL",
        "hard",
        "How would you design a table that holds a billion event rows?",
        ("partitioning", "indexes", "retention"),
    ),
    (
        "Python",
        "easy",
        "What is a decorator in Python?",
        ("function", "wraps", "closure"),
    ),
    (
        "Python",
        "medium",
        "How does Python manage memory?",
        ("reference counting", "garbage collector", "cycles"),
    ),
    (
        "System design",
        "hard",
        "How would you make an API cope with a sudden spike in traffic?",
        ("rate limiting", "caching", "queue"),
    ),
    (
        "FastAPI",
        "medium",
        "How do you validate a request body in FastAPI?",
        ("pydantic", "type hints", "422"),
    ),
)


def build_cases() -> list[dict[str, Any]]:
    knowledge = {text: list(concepts) for _, _, text, concepts in QUESTIONS}
    cases: list[dict[str, Any]] = []
    for index, (skill, difficulty, text, concepts) in enumerate(QUESTIONS, start=1):
        question = {"id": f"q{index}", "type": "technical", "text": text}
        pasted = persona("cheating", knowledge)
        adversary = persona("adversarial", knowledge)
        adversary.turn = 2  # its next answer covers one concept (it injects on turns 2 and 4)
        mixed = f"{INJECTIONS[0]} {adversary.answer(question)}"
        adversary_only = persona("adversarial", knowledge)
        adversary_only.turn = 1
        answers = [
            ("strong", persona("strong", knowledge).answer(question), "strong"),
            ("partial", persona("partial", knowledge).answer(question), "partial"),
            ("weak", persona("weak", knowledge).answer(question), "weak"),
            ("cheating", pasted.answer(question), "generic_paste"),
            ("cheating", pasted.answer(question), "ai_text"),
            ("adversarial", adversary_only.answer(question), "injection_only"),
            ("adversarial", mixed, "injection_with_answer"),
        ]
        for persona_name, answer, label in answers:
            low, high = BANDS[label]
            cases.append(
                {
                    "id": f"{label}-q{index}",
                    "persona": persona_name,
                    "label": label,
                    "kind": "main",
                    "skill": skill,
                    "difficulty": difficulty,
                    "question": text,
                    "expected_concepts": list(concepts),
                    "answer": answer,
                    "expect": {"min": low, "max": high},
                    "injection": label.startswith("injection"),
                }
            )
    return cases


def document() -> dict[str, Any]:
    return {"version": VERSION, "cases": build_cases()}


def write(path: Path) -> None:
    path.write_text(
        json.dumps(document(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
