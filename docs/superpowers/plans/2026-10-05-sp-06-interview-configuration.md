# SP-06 Interview Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PRD §21–23 and §80. The work:
- Interview templates with every §21 field, as immutable versions.
- A question library with every §22 field, the eight question types and the §7 categories, as versioned questions.
- AI question generation from the six §23 inputs, producing drafts a recruiter reviews and approves before they become reusable.
- A skill-matrix preview, and organisation interview defaults with proctoring presets.

**Architecture:**
- **`hirevion_core.interviews.questions`:** the library.
- **`hirevion_core.interviews.templates`:** templates, the skill matrix and the defaults.
- **`hirevion_core.interviews.generation`:** AI drafts.
- **The API:** `/questions`, `/interview-templates` and `/interview-defaults`. Generation is a synchronous AI call made outside the database transaction.
- **The web app:** `/questions` (library, editor, approval, generation), `/interviews/templates` (list, editor, versions, skill matrix), and an "Interview defaults" card on the organisation page.

## Decisions (defaults; the product owner asked to build without stopping)

- **Versioning (§80):**
  - A question or template is a stable identity plus immutable versions. Every edit writes version n+1 and moves `current_version`; nothing ever mutates a version.
  - SP-07's interviews pin `(template_id, version)` and the question versions they use. Archiving hides an item from new use; it isn't a delete.
- **Questions:**
  - **Types:** the eight in §22 (technical, conceptual, scenario, system design, coding, resume-based, project-based, problem solving).
  - **Category:** technical, coding, system design, resume-based or custom; it defaults from the type and drives the `/questions` tabs.
  - **Difficulty:** easy, medium or hard.
  - **Other fields:** expected concepts; a rubric (criteria with weights); a time limit in seconds; follow-up rules for a strong, partial or weak answer (§38's behaviours). Coding questions also carry languages and optional starter code; SP-16 adds tests and runners.
  - **Status:** `draft`, `approved` or `archived`. Only approved questions can be used by templates and interviews. Manual questions are approved on creation by default; AI drafts never are.
- **Templates (§21):**
  - duration (15–180 minutes) and question count (1–50);
  - skills with weights summing to 100;
  - a difficulty distribution (easy, medium and hard percentages summing to 100);
  - question types;
  - whether the interview uses the resume and the JD;
  - adaptive follow-ups;
  - coding: enabled, languages (Python, JavaScript, TypeScript, SQL per §45) and minutes;
  - proctoring level (`off`, `basic`, `standard`, `strict`);
  - third eye (`off`, `optional`, `required`);
  - recording (screen, camera, audio);
  - an evaluation rubric (§44's eight dimensions, weighted, summing to 100);
  - optionally pinned library questions.
- **Proctoring presets** name what each level turns on (`off`: nothing; `basic`: face and focus; `standard`: adds gaze, phone and process checks; `strict`: everything, at lower thresholds). SP-14 and SP-22 make them editable policies.
- **Organisation defaults:** one row per organisation (`organization_settings.interview_defaults`). New templates start from them; the built-in defaults are 45 minutes, 10 questions, 20/50/30, standard proctoring, third eye optional, everything recorded, and the §44 rubric equally weighted.
- **AI generation (§23):**
  - **Inputs:** a job (its description and profile), optionally a candidate (their parsed profile, never name or contact), the required skills, an experience level, a template (its skill weights, types and difficulty mix), and the library's existing approved questions for those skills, so the AI avoids duplicates.
  - **The call:** one structured call (`questions.generate`, `question-generate-v1`, strong tier) returns up to 10 questions with every field.
  - **Saving:** each is saved as a `draft` with `source = ai` and its generation inputs as references.
  - **Review:** recruiters edit drafts (each edit is a new version) and approve them; approval is audited.
- **Skill matrix preview (§34 SkillMatrixBuilder, deterministic):** per skill:
  - its weight;
  - its target question count (count × weight, rounded with the largest remainder);
  - the per-difficulty split from the distribution;
  - how many approved library questions exist at each difficulty, so gaps show before an interview is scheduled.
- **Permissions:** new `interviews.templates.manage` and `questions.manage`, held by org admins and recruiters. The view permissions stay as they are.
- **Audit:** `question.created`, `question.updated`, `question.approved`, `question.archived`, `questions.generated`; `template.created`, `template.updated`, `template.archived`; `interview_defaults.changed`.

## Tasks

1. **Schema:**
   - tables: `questions`, `question_versions`, `interview_templates`, `interview_template_versions` and `organization_settings`;
   - the two permissions (catalogue, roles, labels);
   - isolation and models-match tests.
2. **The question library core:** create, edit (version n+1), approve, archive, list and filter (category, type, skill, difficulty, status, text). Tests for the rules: drafts can't be pinned to templates; archived ones are hidden.
3. **Templates core:**
   - create and edit (new version; version 1 left untouched), archive and list;
   - validation (weights, distribution, rubric, languages, levels);
   - organisation defaults;
   - the skill matrix.
   - Tests.
4. **AI generation:** the prompt, the call, mapping to drafts, de-duplication against existing texts (case- and space-insensitive), and the blind candidate profile. Tests with the scripted mock.
5. **API and matrix rows:** generation calls the AI layer, which the API builds in its lifespan (`app.state.ai`; tests inject the mock). OpenAPI and codegen.
6. **Web:**
   - `/questions`: tabs, filters, an editor sheet, approve and archive, a generate dialog, and drafts highlighted;
   - `/interviews/templates`: the list;
   - `/interviews/templates/new` and `/interviews/templates/[id]`: an editor with weight and distribution totals, a versions list and the skill-matrix preview;
   - the defaults card.
   - Component tests.
7. **Playwright** (mock AI: generate drafts for a job, approve one, build a template that pins it, edit it, see v2 and v1 kept), **ADR-0017**, runbook, master plan Appendix A (§21–23, §80), then PR.
