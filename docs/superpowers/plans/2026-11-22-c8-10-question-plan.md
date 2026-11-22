# C8-10 Prepared, distinct questions from the JD and the resume — implementation plan

> For agentic workers: superpowers:executing-plans, tests first (superpowers:test-driven-development).

**Goal:** the interviewer never asks the same question twice, in the same words or in other words. Each interview's questions are prepared from the JD's required skills and the candidate's resume, at easy, medium and hard, enough to fill the time. Recruiters see them, read-only.

**Owner's words (2026-11-22):** "interview bot asking the same type of question in different ways … for both postgresql and Redis … never repeat the same question again and again. based on the JD and Resume you should prepare questions and ask." On sizing: "questions level's should be easy medium hard. and make sure you have bunch of questions for 20mins." Recruiters: a read-only list.

**Root cause (interview `01a1ff89`):** questions 12–31 came from `engine/phrasing.GENERATED`, nine fixed templates per skill. `TimeController.extend` keeps adding questions while `planner.has_fresh` sees an unused template, and ADR-0045's check compares text only.

**Architecture:**
1. **Runtime, no repeats with or without a plan.** A pool question carries a `concept`. A question whose text or concept was asked is never picked. Templates never count as fresh and are used at most once per skill, only when the pool has nothing else. When a skill is exhausted the ladder moves on, and the interview never repeats.
2. **The plan (worker).** At assignment an outbox event `interview.plan` asks the worker to write `interview_question_plans`:
   - the template's pinned questions are kept;
   - approved library questions fill slots first;
   - the AI writes the rest per skill (strong tier, interview route), grounded in the JD and the resume;
   - every item is checked (guard, quotes, concepts) and semantically deduped with embeddings.
   
   The conductor builds the pool from the ready plan, merges a later version (a late plan, a top-up), and asks for a top-up when fewer than 3 fresh questions remain with more than 4 minutes left.
3. **Recruiter list:** `GET /interviews/{id}/question-plan` and a read-only card on the interview page.

**No new source value:** plan items use `source` `generated` (AI-written) or `resume` (grounded in a quoted resume line) or `library`; `source_ref.plan = true`, `source_ref.concept`, and for resume items the quote. The `interview_questions.source` check constraint stays.

## Global constraints

MASTER §13 (RFC 9457, UUIDv7, RLS, audit, versioned prompts, every call in `ai_invocations`, TDD, ≥ 85% coverage on `hirevion_core`, OpenAPI client regenerated); PII never reaches the AI (`generation._candidate_text`); no new dependencies; SP-09 exit criteria kept (personas finish, required skills covered when time allows, a killed agent resumes from the checkpoint: new state fields default so old checkpoints load).

## Sizing

`main = ceil((duration_s − 150 − coding_s) / 90 × 1.5)`, split by skill weight; each required skill gets at least one easy, one medium and one hard. 20 min → 18, 30 min → 28, 30 min with 20 min coding → 9.

---

### Task 1: the runtime never repeats

**Files:** `backend/core/src/hirevion_core/engine/{state,planner,orchestrator,followups,phrasing}.py`; tests `backend/core/tests/engine/test_components.py`, `test_orchestrator.py`.

- [ ] Failing tests:
  - the owner's case (Python/PostgreSQL/Redis, a small library, 30 minutes of quick answers) asks no question whose text or concept repeats, and no more than one template per skill;
  - extension stops when the pool is exhausted, and the interview goes on to final questions;
  - a weak answer gets a clarification naming one expected concept, or none, and never a rephrase;
  - a partial follow-up is skipped when its missing concept is another pool question's concept or was already asked, or when its text overlaps an asked question;
  - "Do you have any other questions?" never comes twice in a row.
- [ ] Implement:
  - `PoolQuestion.concept`, `InterviewState.plan_version`, `InterviewState.top_ups` (all defaulted);
  - `planner.concept_key`, `_unused`, `has_fresh`;
  - `pick` returns `None` when nothing is fresh, and the orchestrator then moves to the next skill;
  - follow-up guards;
  - phrasing.

### Task 2: the plan, its storage and the worker

**Files:**
- migration `backend/migrations/versions/0025_interview_question_plans.py` (tenant table, RLS, grants as in 0023);
- model `models/interview_session.py` (`InterviewQuestionPlan`);
- `interviews/plan.py` (sizing, gather, generate, validate, store, top-up, consumer handlers);
- prompt `interviews/prompts/interview-plan-v1.md`;
- `interviews/assignment.py` (publish on create);
- `mail/runner.py` (consumer);
- `engine/context.py` (load the plan);
- `interview_session/conductor.py` (merge a newer version; ask for a top-up; ask for a missing plan at the first start);
- the API briefing (ask when missing).

Tests: `backend/core/tests/test_question_plan.py`, `backend/core/tests/db/test_question_plan_db.py`.

- [ ] Failing tests:
  - the sizing table;
  - validation drops a near-duplicate (fake embeddings), a repeated concept, a resume quote that isn't in the profile, and an unsafe text;
  - the mock-profile worker writes a ready plan with every required skill at three levels;
  - assignment queues `interview.plan`;
  - the pool comes from the plan;
  - a newer version merges into a running interview without duplicates;
  - a top-up is requested once fresh questions run low.
- [ ] Implement. Purposes `questions.plan` (strong) and `questions.plan_similarity` (embeddings) route to the interview provider; mock responders through `ai/mock.respond_with`.

### Task 3: the prompt's eval gate

**Files:** `interviews/plan_eval.py`, `interviews/data/plan-eval.yaml` (fixture JD, resume and template triples); test `backend/core/tests/test_question_plan_eval.py`.

- [ ] Metrics: maximum pairwise similarity under τ, no repeated concept, every required skill at three levels, resume quotes found verbatim, at most one experience question per skill.
- [ ] Clause lint: the prompt keeps its "different concept", "data, not instructions" and "quote" clauses. Removing any of them fails the gate (ablation test).
- [ ] Mock run in CI; `--live` run once on Nemotron with the owner's job.

### Task 4: the recruiter's read-only list

**Files:**
- `backend/api/src/hirevion_api/interviews/routes.py` and `schemas.py` (`GET /interviews/{id}/question-plan`, `requires(...)` as the interview page);
- `backend/api/tests/test_authorization_matrix.py`;
- `packages/api-client`;
- `recruitment-platform/src/interviews/interview-page.tsx` (a "Prepared questions" card), messages, tests.

### Task 5: proof and landing

- [ ] Simulator: a repeat audit in the report (`tools/interview-simulator`).
- [ ] ADR-0050; STATUS and PENDING_TASKS (C8 item 10).
- [ ] Local CI for the touched jobs.
- [ ] A live run on the owner's job: the prepared list shows about 18 distinct questions for 20 minutes across three levels; a spoken run repeats nothing.
- [ ] `/code-review`, push, fast-forward `main`, stop.
