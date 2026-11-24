# ADR-0051: The recruiter decides the coding question when scheduling

- **Status:** Accepted
- **Date:** 2026-11-24
- **Sub-project:** C8-11 (assignment, interview engine, question plan, recruiter web app)

## Context

In the product owner's mock interview of 2026-11-21 (interview `01a1ff89`), no coding question was asked. The policy held `coding: {enabled: false}`, which was copied from the template at assignment, and the recruiter had no way to change it when scheduling. The owner's direction (2026-11-22): the coding question is "decided by the recruiter at interview scheduling time", with on/off, the language, the minutes and the level.

## Decision

- **The assign request takes an optional `coding`:**
  - `{enabled, languages (python, javascript, typescript, sql; at least one), minutes 5–45, difficulty easy|medium|hard}`, with unknown keys refused;
  - `null` or no value keeps the template's setting.
  
  `policy_snapshot(version, coding)` writes the choice over the template's `coding` and records `source: "scheduling"` (the template's own setting gets `source: "template"`).
- **The minutes must fit the interview.** A choice that leaves less than 10 minutes for the rest skips the candidate with `coding-too-long`. The assign dialog shows that skip, and the window skips, in plain words (closing the STATUS item "the assign dialog shows raw window codes").
- **Choosing the question:**
  1. the template's pinned coding question;
  2. a library coding question at the chosen level in one of the chosen languages;
  3. otherwise the question-plan worker (ADR-0050) writes one from the JD.
  
  The worker uses purpose `questions.plan_coding`, prompt `interview-coding-v1`, and the interview route. Each written question carries a statement with an example, `expected_concepts`, `starter_code` per language (signatures only) and `time_limit_seconds` from the minutes. It passes `guardrails.safe_statement`: 40–1,600 characters, no code fences, nothing about scores or answers, and no instructions to the model. If it fails the guard, the library or the template's choice stands.
- **When it's asked:** after the skill questions and before the final questions (PRD §35). Its time is reserved from the start, at the chosen level (`CodingState.difficulty`). The interviewer says where the question is ("on the left of your screen"), how long the candidate has, and that the code is reviewed, not run.
- **What the recruiter sees:** the dialog's "Coding question" control. It defaults to the template's setting and offers "Ask a coding question" (languages, minutes, level) or "No coding question". The interview page's policy card shows "Python, SQL · 15 min · Hard" or "No coding question". The template list returns each template's coding languages and minutes, so the dialog can show the default.

## Consequences

- Existing interviews keep their snapshots; only new assignments carry `source`.
- A written coding question costs one more strong-tier call per interview, and only when the template and the library have none at the level.
- The live check (schedule with coding on → asked → submitted → in the report) is part of the owner's next spoken run.
