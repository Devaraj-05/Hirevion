# ADR-0016: Screening and ranking: weighted factors, verified evidence, blind by default

- **Status:** Accepted
- **Date:** 2026-10-05
- **Sub-project:** SP-05

## Context

- **PRD §15–18** ask for:
  - screening from the job, its profile, the resume and a configuration;
  - nine evaluation factors, combining rules, semantic matching, skills, experience, embeddings and AI reasoning;
  - an explainable ranking with evidence for every major factor;
  - configurable weights;
  - workflow stages, recruiter actions, and audited overrides.
- **Master plan §3.2(1) and §6.7** add blind screening by default, knock-outs that never reject, reproducible results, and per-organisation fairness of AI usage.
- **The product owner** asked to build without pausing for decisions; the defaults below are recorded so they can be revisited.

## Decision

- **Factors and default weights** (PRD §17), whole numbers summing to 100, each 0–100:
  - required skills 35;
  - experience 25;
  - projects and relevant roles 15;
  - preferred skills 10;
  - domain 10;
  - education 5;
  - location and work model 0 (off unless configured).
- **The configuration** is an organisation default, overridable per job (`screening_configs`), versioned on each save.
- **Deterministic where possible:**
  - **Skills:** matched by taxonomy id or name. Required skills earn full credit, or half when the candidate has fewer years than asked. Optional skills count half within the preferred score.
  - **Experience:** 70% years against the job's minimum (linear below it), 30% the AI's role relevance. Exceeding the maximum is a concern, never a penalty.
- **One AI assessment per application** (`screening.assess`, `screening-assess-v1`, strong tier):
  - it scores roles, projects, domain, education and location, with quotes from the resume, plus strengths, concerns and missing requirements;
  - quotes are verified against the resume;
  - a factor with no verified evidence is capped at 50 and marked unsupported (education and location may score without quotes when the job asks nothing of them).
- **The match score** is the weighted mean. Ties are broken by the cosine similarity of the job and candidate embeddings, then by who applied first.
- **Blind by default:** the AI sees the resume without name, contact details, links, the personal-details section, dates of birth, or family, marital, religion and caste lines.
- **Knock-outs only flag:** missing required skills, or below the minimum experience. They never reject.
- **Reproducibility:** results are immutable and keyed by resume SHA-256, job version, configuration source and version, prompt and model. Screening again with the same key reuses the result, with no AI call.
- **Workflow:**
  - screening moves `parsed → screened`;
  - once none of a job's applications is waiting, the screened ones become `ranked`, numbered in `applications.rank`;
  - recruiters shortlist, reject, hold, review, and assign a recruiter or hiring manager, singly or in bulk;
  - every change writes `application_history` (with the score and rank at the time) and an audit entry;
  - a rejection, or a decision against the ranking (shortlisting from the bottom half, rejecting from the top quarter), needs a reason and is marked `override`.
- **"Create interview"** belongs to SP-07, which owns interviews.
- **Export** (CSV and XLSX) needs a recent password (step-up) and is audited. Cells that a spreadsheet would run as formulas are neutralised.
- **Background work:** screening runs on a `screening` stream consumer (ADR-0015's delivery rules), one event per application, so organisations interleave. AI spend goes through the per-organisation budget.
- **Evaluation:** `hv eval-screening` ranks the synthetic set's candidates for three role-family jobs and reports NDCG@10 against labels from their true skills. The target is mean NDCG@10 ≥ 0.80, measured with Gemini once its key works.

## Consequences

- **Explainable:** every score shows its factors, the quotes behind them, and what's missing. Recruiters can see why someone ranks where they do, and the AI can't silently invent a strength.
- **Deterministic skill scoring is cheap and stable.** The AI is only used where judgement is needed, and results are reused until something they depend on changes.
- **Blind mode hides names from the AI only.** Recruiters still see names, which bias training and SP-21's adverse-impact view have to address.
- **Watch:**
  - the cap on unsupported factors, in case it under-scores candidates whose resumes are terse;
  - ranking agreement with recruiters' decisions (SP-21's "screening quality" KPI).
