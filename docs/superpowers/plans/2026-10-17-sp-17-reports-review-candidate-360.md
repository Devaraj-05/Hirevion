# SP-17 Reports, review and Candidate 360 (A5) Implementation Plan

**Goal:** PRD §19, §20, §68–§72, §97–§99 (master plan §6.13, §14 SP-17). A report is built once as data, shown on the web and rendered as a PDF; a reviewer works one interview on one timeline; a person, never the AI, decides. Decisions are in [ADR-0023](../../architecture/adr/0023-reports-review-and-hiring-workflow.md).

## Decisions

- **A report is a document of blocks** (`text`, `list`, `facts`, `table`, `quotes`, `notice`), built by `hirevion_core.reports.*`. The web's `ReportView` and the PDF's HTML renderer read the same document, so a section has one source. Each section says `populated`, `empty` or `pending` (coding waits for SP-16 and says so).
- **PDF:** Jinja2 (autoescape) → standalone HTML with a no-network CSP → Playwright Chromium (JavaScript off, every request aborted) → `report_exports` (SHA-256, blob under `{org}/interviews/{id}/report/`). Viewing, exporting and downloading are audited. No Chromium means `503 pdf-unavailable` and the web view still works.
- **Five reports:** interview (13 §69 sections), proctoring (14 §68 sections, counts per kind and the reviewers' outcomes, never one score), coding, internal candidate, candidate-visible (`reports`: one row per interview, drafted from the evaluation without numbers or integrity signals, edited and approved by a recruiter, frozen at release, shown to the candidate only from the portal's `/portal/report`).
- **Scores:** the AI's evaluation is never edited. A change is an insert-only `score_changes` row with a reason (`score.modified`); reports show both.
- **Hiring workflow (§72):** `applications.hiring_status` beside the screening `stage`, every change in `application_status_history`. Stage changes sync it (`record_stage`); `interview_invited/started/completed` are system-only; `selected` and `rejected` after an interview need `hiring.decide`. Hiring Manager input (`hiring_inputs`) is a recommendation with a rationale and never moves the status.
- **Review workspace:** one clock (ms since the interview began); transcript, evidence and events seek it; each track's timeline map turns it into a file position (`review/sync.ts`). The pending-review queue and the pipeline board's moves use the same status API.
- **Candidate 360:** `GET /candidates/{id}/360` returns the blocks the caller may see (13 tabs); `GET /candidates/{id}/timeline` unifies §98's eight sources.

## Tasks (tests first)

1. Migration 0021, models, grants/RLS tests; `hirevion_core.hiring` (status sync, transitions, decision, inputs, notes, score changes).
2. Report builders, HTML and PDF; candidate-visible drafting and release; unified timeline.
3. API: reports and exports, candidate-visible report, review (media, notes, inputs, scores, status, queue, pipeline), Candidate 360, portal report; permissions and matrix rows.
4. Simulator sends proctoring telemetry and recording segments; `hv audit-tail`.
5. Web: reports, review workspace and player, Candidate 360 tabs, queue, pipeline moves, portal report, admin setting.
6. CP3 golden-path Playwright spec; docs (ADR-0023, runbook, threat model, Appendix A, STATUS, PENDING_TASKS).

## Files

`backend/core/src/hirevion_core/{hiring,reports}/`, `models/reporting.py`, `backend/migrations/versions/0021_reports_review.py`, `backend/api/src/hirevion_api/{reports,review,candidate360}/`, `portal/routes.py`, `recruitment-platform/src/{reports,review,candidates,dashboard,portal}/`, `recruitment-platform/e2e/auth/golden-path.spec.ts`, `tools/interview-simulator`, `tools/devcli`.

## Tests

Schema (RLS, insert-only, constraints); workflow (sync, transitions, decision permission, history); documents (13 and 14 sections from a completed interview, confidentiality of the candidate-visible and portal documents); HTML escaping; PDF is a PDF with the report's text; API (scope, permissions, audit `report.viewed/downloaded`, `recording.viewed`, `score.modified`); matrix; web (ReportView, sync mapping, workspace, 360 tabs, pipeline move, portal report); e2e golden path with axe.
