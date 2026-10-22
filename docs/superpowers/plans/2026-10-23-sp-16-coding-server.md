# SP-16 Coding answers, server side (C6) Implementation Plan

**Goal:** PRD §45–§48 as re-scoped by the product owner on 2026-10-23: the AI asks the coding question, the candidate types code in a plain text console and submits it, and the code is evaluated after the interview by an AI review that reads it. **Nothing is executed**: no sandbox, no Run, no test cases, no measured runtime or memory. The desktop's console is B4; this part makes its API complete. Decisions are in [ADR-0033](../../architecture/adr/0033-coding-answers-without-execution.md).

## Decisions

- **Answers:** `coding_submissions` (insert-only) holds every submission: the code, its language label, size, SHA-256 and time, with its source: the candidate's Submit, the question's time limit, or the question closing another way (then the last autosaved snapshot becomes the final code). The final code of a question is its latest submission.
- **Engine:** `CodingController` keeps §34's coding state (the question, its submissions, how it ended). The AI asks the question and tells the candidate to type in the text box and submit. A submission closes the question in a conductor turn, without answer analysis, and the interview moves on; the time limit closes it the same way.
- **Evaluation (inside C4's `hirevion_core.evaluation`):** one strong-tier call per coding question, prompt `evaluation-coding-v1`, rubric `coding-v1` with fixed weights (pinned with the evaluation like the others). Seven criteria: correctness of the logic, approach, edge cases considered, time and space complexity (the model's estimate, labelled "estimated"), code quality, readability. Every criterion cites quotes from the code, verified against it with line numbers; a criterion without a verified quote is capped at 5 and flagged. The result fills the evaluation's coding slot. The mock grader reads code deterministically and follows the prompt as written; the eval gate adds a labelled coding set.
- **Integrity telemetry (§48 subset):** typing started/stopped, paste, copy, cut, focus, blur, with the pasted, copied or cut length only, never the text; no keystrokes. Shown to reviewers as signals, never proof.
- **Reports:** the coding report shows each question, the final code, every submission, the AI's assessment with its evidence and the integrity signals; the interview and candidate reports and the Candidate 360 Coding tab summarise it.

## Tasks (tests first)

1. Migration 0022 and models; schema tests (RLS, insert-only).
2. Engine and conductor: submit, time limit, auto-final; `hirevion_core.coding` (question view, submissions, telemetry, signals).
3. API: `GET /interviews/{id}/coding`, `POST …/coding/submissions`, `POST …/coding/telemetry`.
4. Evaluation: coding prompt, rubric, evaluator, evidence, mock grader, slot, pin and re-run; gate set and baseline.
5. Reports, Candidate 360 and evaluation API; web Coding tab and evaluation card.
6. Simulator submits code; contract `coding.md`; ADR-0033, master plan §6.10, §14 SP-16 and Appendix A, runbook, threat model, PENDING_TASKS (C6, B4), STATUS.

## Files

`backend/migrations/versions/0022_coding.py`, `models/coding.py`, `hirevion_core/coding/`, `engine/{coding,state,orchestrator,phrasing}.py`, `interview_session/conductor.py`, `evaluation/{coding,mockgrader,registry,inputs,aggregate,service,harness}.py` with `prompts/`, `rubrics/`, `eval_set/`, `reports/{coding,interview,candidate}.py`, `hirevion_api/{coding,candidate360,evaluation}/`, `tools/{devcli,interview-simulator}`, `recruitment-platform/src/{candidates,interviews}/`.

## Tests

Schema; engine (submit closes and advances; time limit stores the snapshot); API (DPoP scope, wrong question, language not offered, size, telemetry kinds and limits, no content accepted); evaluator (evidence verified with lines, cap, injection in a comment, empty code); gate (coding metrics, each clause removed is caught); reports and 360 (sections populated); web components; simulator interview with coding end to end.
