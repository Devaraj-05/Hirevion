# ADR-0031: Evaluation and AI governance: verified quotes, rubric-weighted scores, pinned versions and a gate

- **Status:** Accepted
- **Date:** 2026-10-10
- **Sub-project:** SP-10

## Context

- **PRD §44** asks for eight dimensions (relevance, correctness, completeness, technical depth, reasoning, clarity, communication, evidence) and says "store evidence rather than only a score". **§70** asks for per-skill scores, communication and the like in a final evaluation, "each score must have supporting evidence". **§79** lists eight governance fields (model name and version, prompt, rubric and evaluation versions, timestamp, input references, output) so that evaluations are auditable and reproducible.
- **Master plan §6.9** splits the work: a live `AnswerAnalyzer` steers the conversation (SP-09, ADR-0030), and an async `QuestionEvaluator` scores afterwards. Prompts and rubrics are versioned files; a change activates only after the eval harness.
- **Screening** already solved "a score must have evidence" for resumes (ADR-0016): quotes are checked against the source, and a factor without a verified quote is capped.
- **The inputs are hostile.** The candidate's words reach a model that sets a number a recruiter will read. ADR-0030 left this for SP-10: "the evaluator must treat answers as untrusted in the same way".
- **The real vendor key is unusable today** (Gemini), so everything that gates a change must run on the mock profile in CI.

## Decision

- **One call per answered question** (`evaluation.question`, strong tier, prompt `evaluation-question-v1`) returns the eight dimensions, each a score from 0 to 10 and one to three quotes, plus the concepts missed and a short note.
  - Main and follow-up questions with a stored answer are scored. The introduction, the final questions and coding are not (coding is SP-16's).
  - Only candidate transcript turns that match a stored answer are sent. A repeat request or an attempt to instruct the AI is in the transcript but never reaches the evaluator or becomes evidence.
  - A follow-up also sees the main question and its answer as context. Quotes may come only from the question's own answer.
- **Verified evidence.**
  - A quote is accepted when, ignoring case, spacing and the style of quotes and dashes (`documents.quotes.fold`, as in screening), it is at least six characters and sits inside one candidate turn of that question. It then carries the turn's number and times (`start_ms`, `end_ms`).
  - Quotes that fail are dropped. A dimension left with none is **capped at 5.0 and flagged `unsupported`**; the raw score is kept beside it.
  - A skill whose questions have no supported dimension at all is flagged too, and so is a gap. A strength with no verified quote is dropped.
- **The rubric.**
  - The anchors and definitions are a versioned file (`dimensions-v1`). The weights are the template's (SP-06), pinned in the interview's policy; a question's score is the mean of its eight scores weighted by them.
  - `rubric_version` is the anchors' name plus a digest of the weights in force (`dimensions-v1+w36137962`), and the weights themselves are stored with the evaluation.
- **Aggregation (§70), `EVALUATION_VERSION = evaluation-v1`.**
  - A skill's score is the mean of its questions' dimension scores (a follow-up counts for half a main question), then rubric-weighted.
  - The overall score is the skills' mean by the weights the interview was planned with; a skill nothing was scored on is listed, not scored.
  - Communication is the communication dimension across all questions.
  - Follow-up performance compares follow-ups with main questions numerically.
  - Coding is a slot, `pending` until SP-16.
  - One synthesis call (`evaluation.synthesis`) writes strengths, knowledge gaps, a follow-up summary and a communication summary; its quotes are verified against every candidate turn of the interview.
- **Lifecycle and delivery.**
  - Completing an interview queues an `evaluation` event in the same transaction (`lifecycle.transition`). `interview.completed` cannot be shared: stream consumers delete what they finish, so a second group would lose it.
  - Three steps with no transaction open during a model call: (1) `completed → evaluating` and a `running` evaluation row with the versions in force; (2) the calls; (3) the scores, `evaluating → evaluated` and `evaluation.completed` (ids, status, overall score and versions; no personal details) in one transaction.
  - A failure marks the evaluation failed and leaves the interview Evaluating; the stream retries (five attempts); the last attempt's give-up returns the interview to Completed. Any failed call, including an unusable reply, fails the run so it is redone whole; an evaluation is never stored with questions missing.
  - A partial unique index allows one running or ready initial evaluation per interview, and a `running` row that has not been touched for three minutes (a live run touches it after every question) can be replaced; the questions run at most four at once, and any unusable reply fails the whole run so it is redone.
- **Governance (§79).**
  - Every call goes through the provider layer's `Recorder`, so `ai_invocations` already holds the eight fields; no column was added. The context carries the prompt, rubric and evaluation versions, and `input_refs` names the interview, the evaluation, the question and the SHA-256 of the request.
  - `evaluations` pins what a re-run needs: the prompt names, the rubric's base and weights, the skill plan, the models and the input digests.
  - **Pinned re-run** (`hv eval-rerun`, or an admin's request on the interview's page) loads those names and weights, evaluates again and stores a `rerun` evaluation with the difference: per dimension, per question and overall, against a tolerance of 1.0 on a dimension and 0.5 on a question or the overall score. It also lists questions whose input changed and says whether the model differs. It refuses an evaluation version this software cannot reproduce. The interview's status and original evaluation are untouched.
  - Temperature is left at the provider's default (Gemini 3 advises against lowering it), so the contract is "within tolerance", not "identical".
- **The gate (`hv eval-interviews`).**
  - A labelled set of 42 answers: the simulator's personas (strong, partial, weak, a generic paste, AI-sounding text, an injection alone, an injection with an answer) over six questions, each with the band its score belongs in (`eval_set/cases.json`; a test ties it to the personas).
  - Metrics: band hit rate, weighted kappa and Spearman against the bands' midpoints, the share of dimensions with verified evidence, injection resistance, p95 latency.
  - It blocks when a metric is under its threshold, when one has fallen more than 0.02 from the committed baseline, or when the prompt has lost a required clause (data not instructions, quotes character for character, score anchors).
  - **On the mock profile the grader follows the prompt as written** (`mockgrader`): without the verbatim clause it paraphrases, without the anchors its scores drift to the middle, without the data clause it obeys the injected instruction. A test swaps in a deliberately bad prompt and sees every one of those blocked, and each clause is also removed alone to show a metric (not only the lint) catches it. CI runs `hv eval-interviews` on every backend change.
  - `--live` runs the same set and thresholds through the configured vendor.
- **Human calibration.**
  - Reviewers (anyone with `reports.interview.view` and the interview in scope) save their own scores per question and dimension; the panel shows the AI's scores beside theirs only once they have saved, and the API keeps other reviewers' scores private.
  - Agreement is the organisation's weighted kappa (quadratic, whole points), Spearman, the mean gap, the share within a point and the AI's bias, overall and per dimension, from the interviews' current evaluations. Its wording needs at least ten pairs.
- **Prompt injection.** The evaluator has no tools. The candidate's words reach it as JSON data under a prompt that says so, behind the provider layer's guard message; its reply is schema-checked, every number is bounded, and every quote must be verified. What an injection can still do is move a number inside the bounds, which the gate's injection cases and the reviewers' calibration watch for. Deterministic manipulation phrases in an answer also add a `manipulation_attempt` flag for the reviewer.

## Consequences

- **Every score can be audited:** the quote, where it was said, the prompt, rubric and model that scored it, and the request's hash. A recruiter sees the cap when a dimension has no verified evidence.
- **Changing a prompt is a deliberate act:** a new file, a gate run, a registry change and a baseline update in one change. The mock run proves the pipeline and the gate, not a real model's agreement; the first `--live` run belongs to the day a vendor key works, and its numbers should replace the mock's in `docs/evals/`.
- **Scoring cost:** one strong call per scored question plus one summary, sequentially. A retry after a late failure repeats the calls already made. Latency is bounded by the gate; if it matters, the questions can run in parallel.
- **Anchoring is reduced, not removed:** reviewers see the overall and skill scores before scoring a question. The per-question numbers they compare against stay hidden until they save.
- **Watch:**
  - the cap of 5 for unsupported dimensions, in case it under-scores terse candidates with real answers (the same trade-off as screening);
  - the tolerance, once real-model re-runs show their spread;
  - agreement per dimension: communication and evidence are the likeliest to disagree with reviewers;
  - the integrity flags (`ai_text_suspected`, `repeated_answer`, `manipulation_attempt`) are signals for a reviewer, never a verdict.
- **Hand-offs:** SP-16 fills the coding slot and the coding criteria; SP-17 reads `evaluations`, `question_evaluations` and `human_scores` for reports and Candidate 360; SP-18 delivers `evaluation.completed`; SP-21 may use the agreement figures as a quality measure.
