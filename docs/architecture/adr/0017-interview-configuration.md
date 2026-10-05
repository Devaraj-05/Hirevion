# ADR-0017: Interview configuration: versioned questions and templates, AI drafts for review

- **Status:** Accepted
- **Date:** 2026-10-05
- **Sub-project:** SP-06

## Context

- **PRD §21–23** ask for:
  - interview templates with 13 settings;
  - a question library with 10 fields, 8 types and §7's categories;
  - AI question generation from six inputs, reviewed before reuse.
- **PRD §80** asks for immutable template versions, so an interview keeps the version it was scheduled with.
- **Master plan §6.8 and §6.18** add:
  - a skill-matrix preview (the deterministic SkillMatrixBuilder);
  - organisation interview defaults;
  - proctoring-level presets.
- **The product owner** asked to build without pausing for decisions; the defaults below are recorded so they can be revisited.

## Decision

- **Identity plus immutable versions**, for both questions and templates:
  - `questions` and `interview_templates` hold what changes in place: status, name, `current_version`.
  - `question_versions` and `interview_template_versions` hold the content and are never updated; the database role has no UPDATE on them.
  - Every edit inserts version n+1 and moves `current_version`.
  - SP-07's interviews pin `(template_id, version)` and the question versions they use.
- **Questions:**
  - **Fields:**
    - text;
    - skill (matched to the taxonomy when it can be);
    - topic;
    - difficulty (easy, medium or hard);
    - type (§22's eight);
    - category (defaults from the type; it drives the `/questions` tabs);
    - expected concepts;
    - a rubric of named criteria whose weights sum to 100;
    - a time limit (30–3600 seconds);
    - follow-up prompts for a strong, partial or weak answer;
    - for coding questions, languages and optional starter code (SP-16 adds tests).
  - **Status:** `draft`, `approved` or `archived`. Only approved questions can be pinned to templates; archived ones are hidden unless asked for, and restoring one makes it a draft again.
  - **Approval:** manual questions are approved on creation unless saved as drafts.
- **Templates:**
  - §21's settings: duration 15–180 minutes; 1–50 questions; weighted skills summing to 100; an easy/medium/hard mix summing to 100; question types; whether to use the resume and the job description; adaptive follow-ups; coding (languages, 5–90 minutes); proctoring level; third eye; recording; and a rubric over §44's eight dimensions summing to 100.
  - **Pinned questions:** optional, each pinned at a version, no more than the question count.
  - **Starting point:** new templates start from the organisation's interview defaults. An update changes only the fields sent; everything else carries over from the previous version.
  - **Names:** case-insensitively unique per organisation.
  - **Archiving** hides a template from new interviews; it isn't a delete.
- **Organisation defaults:** one `organization_settings` row per organisation, validated like a template version. The built-in defaults are:
  - 45 minutes and 10 questions, mixed 20/50/30;
  - standard proctoring, third eye optional, everything recorded;
  - the §44 rubric equally weighted (four dimensions at 13, four at 12).
- **Proctoring presets** name what each level turns on:
  - off: nothing;
  - basic: face and focus;
  - standard: adds gaze, phone, processes and displays;
  - strict: adds audio and the third eye.

  SP-14 and SP-22 turn them into editable policies.
- **Skill matrix:**
  - each skill's share of the questions uses the largest-remainder method, so the counts always sum to the total;
  - each share is split by the difficulty mix the same way;
  - it is compared with the approved library questions for that skill at each difficulty, and the shortfalls are shown;
  - the API previews it for unsaved settings, so the editor shows it live.
- **AI drafts (PRD §23):**
  - **Inputs:** the skills, the experience level and the types asked for, plus optionally a job (title, skills, responsibilities, description), a candidate and a template (skill weights, mix and types).
  - **Candidate data sent:** only titles, companies, skills, projects and achievements; never their name, contact details or personal details.
  - **The library:** up to 40 of its existing questions for those skills are sent, so the AI avoids repeats.
  - **The call:** one structured call (`questions.generate`, `question-generate-v1`, strong tier), made outside any database transaction. It writes up to 10 questions.
  - **Saving:** answers that repeat a library question (comparing case- and punctuation-folded text) or fail the library's checks are skipped and counted. The rest are saved as `draft` with `source = ai` and the model, prompt version and input references.
  - **Rubrics:** a rubric whose weights don't sum to 100 is dropped rather than guessed.
  - **Audit:** the batch is audited as `questions.generated`.
  - **Failures:** an unavailable AI answers 503 `ai-unavailable`; a spent budget answers 429 `ai-budget-exceeded`.
- **API:** the API builds its AI services in its lifespan (`app.state.ai`). Tests inject the mock; missing keys only turn generation off.
- **Permissions:**
  - `questions.view` and `questions.manage`;
  - `interviews.templates.view` and `interviews.templates.manage` (org admins and recruiters hold the manage permissions);
  - the defaults: read with either templates view or `admin.organization.manage`, changed only with `admin.organization.manage`.
- **Audit entries:**
  - `question.created`, `.updated`, `.approved`, `.archived`, `.restored`;
  - `template.created`, `.updated`, `.archived`, `.restored`;
  - `interview_defaults.changed`.

## Consequences

- **Interviews stay reproducible:** a scheduled interview's template and questions can't change under it, and every version can be shown later in its report.
- **Nothing the AI writes reaches a candidate unreviewed:** drafts need a recruiter's approval, and approval is audited.
- **The skill matrix** shows library gaps before an interview is scheduled; SP-09's QuestionPlanner fills them with generated questions at interview time.
- **Watch:**
  - how much the folded-text de-duplication misses (reworded repeats); embeddings can replace it if it matters;
  - template version counts: every save is a version, even one with no change.
