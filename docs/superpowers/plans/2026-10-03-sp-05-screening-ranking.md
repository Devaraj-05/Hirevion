# SP-05 Screening and Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PRD §15–18 and master plan §6.7. Every parsed application of a job gets an explainable, evidence-backed screening result. Results are ranked. Recruiters review, shortlist, reject, hold and assign, singly or in bulk, and every decision is audited.

**Architecture:**
- **`hirevion_core.screening`:**
  - configuration (an organisation default, overridden per job);
  - blind text;
  - deterministic factor scores;
  - one LLM assessment per application, with verified evidence;
  - combination, caching and ranking.
- **Background work:** screening runs on a `screening` stream consumer beside the documents consumer (ADR-0015's delivery rules).
- **Actions:** workflow actions move `applications.stage`, write `application_history` and audit.
- **The API** adds configuration, screening, ranked results, actions (single and bulk) and export.
- **The web app** adds the job's Screening tab (settings) and Ranking tab (results, evidence drawer, bulk actions, export), the organisation's screening defaults, and stage tabs on `/candidates`.

**Tech Stack:** existing only (pgvector, the AI layer, openpyxl added for XLSX export, MIT).

## Decisions (made with defaults; the product owner asked to build without stopping)

- **Weights.** Factors and default weights follow PRD §17:
  - required skills 35, experience 25, projects and relevant roles 15, preferred skills 10, domain 10, education 5;
  - location and work model 0, i.e. off unless configured.
  - Weights are whole numbers that sum to 100.
  - "Technology match" is part of the two skill factors, which also credit `optional` skills at half weight within preferred.
- **Configuration.** Each organisation has one default (`screening_configs` with `job_id` null). A job can override it. Each save increments `version`, and results record the version used.
- **Scoring:**
  - **Skill factors are deterministic:**
    - a skill counts as matched by taxonomy id, or by name ignoring case;
    - each required skill gets full credit, or half credit when the candidate has the skill but fewer years than its `min_years`.
  - **Experience is mostly deterministic, with an AI part:**
    - 70% comes from years against the job's minimum (full at or above it, linear below it, never penalised for exceeding the maximum, which only raises a concern);
    - 30% is the AI's role-relevance score.
  - **The AI factors:** projects and roles, domain, education and location come from one AI assessment (`screening.assess`, prompt `screening-assess-v1`, tier `strong`). It returns, for each factor, a 0–100 score and evidence quotes from the resume, plus strengths, concerns and missing requirements.
  - **Evidence checks:** quotes are verified against the resume text. A factor score with no verified evidence is capped at 50 and marked `unsupported`.
  - **Semantic similarity:** the cosine similarity of the job and candidate embeddings is recorded, shown, and used to break ties in the ranking.
  - **The match score** is the weighted mean, rounded to a whole number.
- **Blind mode** is on by default:
  - the AI sees the resume with its name, email, phone, links and personal-details section removed, and dates of birth masked;
  - the AI never sees the candidate's name;
  - the ranking UI still shows names, since recruiters already have them.
- **Knock-outs never reject.** A required skill missing, or experience below the minimum, adds a `knockout` flag to the result.
- **Reproducibility.** A result is cached by (resume SHA-256, job version, configuration version, prompt version, model). Screening again with the same key reuses it with no AI call.
- **Workflow (PRD §18 stages):**
  - screening moves `parsed` to `screened`;
  - when a job's screening run finishes, its screened applications become `ranked`;
  - opening an application's evidence doesn't change its stage; "Review" moves it to `review` explicitly;
  - shortlist, reject and hold set `shortlisted`, `rejected` and `on_hold`;
  - "Create interview" arrives with SP-07, which owns interviews; Appendix A says so.
- **Audit.** Every stage change writes `application_history` (from, to, by, reason, score and rank at the time) and an audit entry (`application.shortlisted`, `rejected`, `held`, `reviewed`, `assigned`). A decision against the AI's ordering is recorded with `override: true`: shortlisting from below the top half, or rejecting from the top quarter.
- **Assignment.** Each application can have its own recruiter and hiring manager, defaulting to the job's.
- **Export.** CSV and XLSX of the ranked results, behind step-up (master plan §9: exports need a recent password), and audited (`screening.exported`).
- **Permissions:**
  - `candidates.view` reads results;
  - `candidates.manage` screens and takes actions;
  - `jobs.create` edits a job's configuration;
  - `admin.organization.manage` edits the organisation default.
- **PRD §90 endpoints** exist as written: `POST /jobs/{id}/screen`, `GET /jobs/{id}/screening-results`, and `POST /candidates/{id}/shortlist` and `/reject` with a `job_id` body.
- **Fairness and budgets.** Screening calls go through the AI layer's per-organisation budget. The consumer screens one application at a time per event, and a job's run is one event per application, so organisations interleave.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/migrations/versions/0011_screening.py` | `screening_configs`, `screening_results`, `application_history`; applications gain `recruiter_id`, `hiring_manager_id`, `screening_result_id` |
| `backend/core/src/hirevion_core/models/screening.py` | ORM models |
| `backend/core/src/hirevion_core/screening/{config,blind,factors,assess,engine,runner,workflow,export}.py` | The pieces above |
| `backend/core/src/hirevion_core/screening/prompts/screening-assess-v1.md` | The versioned prompt |
| `backend/api/src/hirevion_api/screening/{schemas,routes}.py` | Routes |
| `recruitment-platform/src/screening/**` | Ranking, settings, defaults |
| `tools/devcli/src/hirevion_devcli/screening_eval.py` | `hv eval-screening` (ranking agreement on the synthetic set) |

---

### Task 1: Schema

- **`screening_configs`:**
  - columns: `organization_id`, `job_id` (nullable; unique per organisation including the null default), `weights` (jsonb), `knockouts` (jsonb: `required_skills`, `min_experience` booleans), `blind` (bool), `version`, `updated_by`, timestamps;
  - grants: S/I/U.
- **`screening_results`:**
  - columns:
    - `application_id`, `job_id`, `candidate_id`;
    - `cache_key` (unique per organisation);
    - `job_version`, `config_version`, `prompt_version`, `model`;
    - `score` (int 0–100), `factors` (jsonb), `skill_match` (jsonb), `experience` (jsonb);
    - `strengths`, `concerns`, `missing` (jsonb lists), `knockouts` (jsonb), `semantic_similarity` (float);
    - `created_at`;
  - grants: S/I.
- **`application_history`:** `application_id`, `from_stage`, `to_stage`, `action`, `reason`, `score`, `rank`, `override`, `actor_id`, `created_at`; grants S/I.
- **`applications`** gains `recruiter_id`, `hiring_manager_id` and `screening_result_id`.
- [ ] Tests: isolation, unique default per organisation, the harness, models match migrations. Commit `feat(screening): add configurations, results and application history`.

### Task 2: Configuration, blind text, deterministic factors

- `config.effective(session, job_id) -> Config`; `config.save(session, actor, job_id | None, changes)` validates the weights (keys known, whole numbers, sum 100) and increments the version.
- `blind.blind_text(text, profile) -> str`, with the `personal` and `languages` headings added to section detection.
- `factors.skill_match(job_skills, candidate_skills) -> SkillMatch(required_score, preferred_score, matched, missing_required, missing_preferred)`; `factors.experience_years(job, profile) -> (score, notes)`.
- [ ] Tests for each, with the edge cases: no required skills scores 100; years below the minimum score linearly; an exact taxonomy match beats a name match. Commit `feat(screening): configure weights and score skills and experience`.

### Task 3: The AI assessment, combination and cache

- `assess.assess(llm, organization_id, job_profile_text, blind_resume, *, ids) -> Assessment` (scores and quotes per factor; strengths, concerns, missing; quotes verified).
- `engine.screen_application(session_factory, ai, organization_id, application_id) -> ScreeningResult`: computes or reuses (cache key) the result, links it to the application, and moves the stage `parsed → screened`.
- [ ] Tests with a scripted mock LLM:
  - the weighted score;
  - an unsupported factor is capped;
  - knock-out flags;
  - a cache hit makes no AI call;
  - the blind text has no name, email or DOB.

  Commit `feat(screening): assess, combine and cache screening results`.

### Task 4: Runner, ranking and workflow

- `runner.request_screening(session, actor, job_id, application_ids | None)` queues a `screening` event per application, and audits `screening.requested`.
- `ScreeningConsumer` uses `DocumentConsumer`'s class, generalised over the stream.
- When no application of the job is still `parsed`, screened ones become `ranked`.
- `ranking(session, job_id)` orders by score desc, then semantic similarity desc, then applied date.
- `workflow.act(session, actor, application_ids, action, *, reason, user_id)` covers shortlist, reject, hold, review, assign recruiter and assign hiring manager, with history, audit and override detection.
- [ ] Tests (database). Commit `feat(screening): screen in the background, rank, and act on applications`.

### Task 5: API

- `GET`/`PUT /jobs/{id}/screening-config`; `GET`/`PUT /screening-config` (the organisation default).
- `POST /jobs/{id}/screen` (202).
- `GET /jobs/{id}/screening-results`: the ranked list, paged, with a `stage` filter.
- `GET /applications/{id}/screening`: the full result and evidence.
- `POST /jobs/{id}/applications/actions`: bulk.
- `POST /candidates/{id}/shortlist` and `/reject` (body `job_id`, `reason`).
- `GET /jobs/{id}/screening-results/export?format=csv|xlsx`: step-up.
- `/candidates` gains `stage_group`: `screening`, `shortlisted`, `interview`, `completed`, `decision`.
- [ ] API tests, matrix rows, OpenAPI and codegen. Commit `feat(api): add screening configuration, results, actions and export`.

### Task 6: Web

- **The job page's Screening tab:** weights, knock-outs and blind mode, inheriting the organisation default with a "Use the organisation default" reset.
- **The job page's Ranking tab:**
  - a "Screen candidates" button;
  - progress while applications are `parsed`;
  - the ranked table (rank, name, score, skill match, experience, flags, stage);
  - selection with bulk actions;
  - an evidence drawer showing factor scores with quotes, strengths, concerns and missing requirements;
  - export (step-up).
- **`/admin/organization`** gains a "Screening defaults" card.
- **The `/candidates` stage tabs** filter for real.
- [ ] Component tests: the weights must sum to 100; bulk actions send the ids; the drawer shows evidence; export asks for step-up. Commit `feat(web): screen, rank and act on candidates`.

### Task 7: Evaluation, end to end, docs

- **`hv eval-screening`:**
  - builds three jobs from the synthetic set's skills;
  - labels relevance from the truth (overlap of required skills, plus years);
  - screens with the configured AI;
  - reports NDCG@10 and precision@10 against the labels;
  - target NDCG@10 ≥ 0.80.
  - The live run is later, with Gemini.
- **Playwright (mock AI):** upload two resumes, screen, see the ranking, shortlist one with a reason, see its stage.
- **Docs:**
  - ADR-0016 (screening);
  - runbook;
  - master plan Appendix A (§15–18; "Create interview" → SP-07);
  - push, CI, PR.
