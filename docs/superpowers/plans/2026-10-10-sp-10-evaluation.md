# SP-10 Evaluation and AI Governance Implementation Plan

**Goal:** PRD §44 (answer evaluation, "store evidence rather than only a score"), §70 (the final evaluation, "each score must have supporting evidence") and §79 (the eight governance fields), as master plan §6.9 describes them. Lane C's part C4.

**Out of scope here:** the coding evaluation (§47, SP-16 fills the slot this part leaves), reports and Candidate 360 (SP-17 reads this part's tables), the live `AnswerAnalyzer` (built in SP-09; it steers the conversation and is never reused as a score).

## Architecture

- **`hirevion_core.evaluation`** is the whole part:
  - `registry`: versioned prompt and rubric files (`prompts/*.md`, `rubrics/*.md`), the active names, `EVALUATION_VERSION`, and a lint that checks a prompt still carries the clauses the pipeline relies on.
  - `evidence`: locates a model's quote in the stored transcript segments (the same folding as screening, `documents.quotes`) and returns the segment's number and times. A quote that isn't found is dropped.
  - `scoring.QuestionEvaluator`: one structured strong-tier call per answered question; eight dimensions on a 0 to 10 scale, each with quotes. A dimension without a verified quote is capped at 5 and flagged unsupported. The question's score is the mean of the eight, weighted by the interview's rubric (the template's weights, pinned in its policy).
  - `aggregate`: per-skill scores (rubric-weighted, follow-ups at half weight), communication, the overall score by the skills' weights, the coding slot left pending, and the one synthesis call (strengths, knowledge gaps, follow-up performance, communication summary), whose quotes are verified the same way.
  - `service`: reads the interview, runs the evaluator with no transaction open, then writes the evaluation, the interview's move `evaluating → evaluated` and the `evaluation.completed` event in one transaction. `rerun_pinned` repeats an evaluation with the versions it recorded and reports the difference.
  - `runner`: the `evaluation` stream consumer; `lifecycle.transition` queues its event when an interview completes, in the same transaction.
  - `calibration` and `agreement`: reviewers' own scores per question, weighted kappa and Spearman per organisation.
  - `harness`: the labelled synthetic set, the metrics and the gate (`hv eval-interviews`).
  - `mockgrader`: the deterministic grader behind the mock profile.
- **Tables (migration 0016):** `evaluations` (one per run, with the pinned versions, skills, summary and, for re-runs, the diff), `question_evaluations` (the eight dimensions with evidence), `human_scores`. `ai_invocations` already holds the §79 fields (model, model version, prompt, rubric and evaluation versions, timestamp, input references, output), so it is not extended: each call carries the evaluation, interview and question ids in `input_refs`.
- **API (`hirevion_api.evaluation`):**
  - `GET /interviews/{id}/evaluation` and `/evaluation/questions/{question_id}`;
  - `POST /interviews/{id}/questions/{question_id}/human-scores` and `GET .../human-scores`;
  - `GET /evaluation/calibration`;
  - `POST /interviews/{id}/evaluation/rerun` and `GET /interviews/{id}/evaluation/reruns` (admins).
- **Web:** an evaluation card and a calibration panel on the interview page; their logic (validation, blind-first reveal, agreement wording) is plain functions under Vitest.

## Decisions (defaults; the product owner asked to build without stopping)

- **Scale:** 0 to 10, one decimal, as in §70's example.
- **What is scored:** main and follow-up questions that have a candidate answer. The introduction, the final questions and coding are not (coding is SP-16's). An utterance that isn't an answer (a repeat request, a manipulation attempt) is never sent to the model: only candidate segments that match a stored answer are.
- **Cap:** 5.0 for a dimension with no verified quote, flagged `unsupported`. A skill with no supported dimension at all is flagged too.
- **Verified quote:** at least six characters after folding, found inside one candidate segment of the same question (for the synthesis, any candidate segment).
- **Rubric version** is `dimensions-v1` (the anchors) plus a short digest of the weights in force, because the weights are per interview. The evaluation stores the weights themselves.
- **Evaluation version** (`evaluation-v1`) names the aggregation rules; it changes whenever the arithmetic does.
- **Events:** the completion consumer cannot share `interview.completed`'s stream (consumers delete what they finish), so `lifecycle.transition` queues its own `evaluation` event. `evaluation.completed` is the webhook topic (ids, status and the overall score; no personal details).
- **Failure:** an unavailable model or an exhausted budget retries the whole run (the stream consumer's rules); after the last attempt the interview goes back to `completed` and the evaluation is marked failed. An unusable reply for one question leaves that question unscored and flagged.
- **Pinned re-run:** not a new result. It stores a `rerun` evaluation linked to the original with the per-dimension differences; tolerance is 1.0 on a dimension and 0.5 on a question's or the final score. The interview's status doesn't change. A model name different from the pinned one is reported, not hidden. Provider temperature is left at its default: Gemini 3 advises against lowering it, so tolerance, not determinism, is the contract.
- **Gate:** metrics on the labelled set (band hit rate, rank agreement, evidence-verified rate, injection resistance) against absolute thresholds and the committed baseline. On the mock profile the grader follows the prompt as written: take away the verbatim-quote clause, the score anchors or the data-not-instructions clause and the corresponding metric drops. A real-model run (`--live`) uses the same thresholds.
- **Calibration:** reviewers score before they see the AI's numbers (the panel reveals them after saving); agreement is the organisation's weighted kappa (quadratic, 11 categories), Spearman and the share within one point, over question and dimension pairs.
- **Permissions:** reading and scoring need `reports.interview.view` and the interview's resource scope (reviewers only their own); calibration statistics need `reports.analytics.view`; re-runs need `admin.ai.manage`.

## Tasks (test first, then code)

1. Registry and lint; evidence location. Tests: prompts load, the active prompt passes the lint and a bad fixture fails it; quotes are found across case, quote style and spacing, dropped when invented, scoped to their question.
2. `QuestionEvaluator` and the mock grader. Tests: eight dimensions with verified evidence; an invented quote caps and flags; weights decide the score; an injected instruction doesn't move the score; the request carries only data and no tools.
3. Aggregation and synthesis. Tests: skill and overall arithmetic, follow-up weight, unscored skills, coding slot, unsupported strengths dropped.
4. Agreement statistics (known values).
5. Migration, models, the service and the consumer (database). Tests: interview `completed → evaluating → evaluated`, rows, `evaluation.completed`, `ai_invocations` fields, idempotency, give-up, tenant isolation, the lifecycle queues the event.
6. Pinned re-run (database): reproduces within tolerance; noisy replies are reported as out of tolerance; changed inputs are reported.
7. Harness, labelled set, baseline, `hv eval-interviews`, `hv eval-rerun`, the CI step. Tests: the gate passes now and fails for the bad prompt fixtures; exit codes.
8. API, permissions, authorisation matrix, OpenAPI and the generated client. Tests: reading, scope, scoring, calibration, re-run queueing.
9. Web panel logic and rendering (Vitest).
10. Docs: ADR-0031, runbook, Appendix A rows, the threat model, `PENDING_TASKS.md`.
