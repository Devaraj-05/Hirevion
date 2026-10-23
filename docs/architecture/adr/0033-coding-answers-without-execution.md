# ADR-0033: Coding answers in a text console, reviewed by AI after the interview, never executed

- **Status:** Accepted
- **Date:** 2026-10-23
- **Sub-project:** SP-16 (C6, server side; B4 builds the desktop console)

## Context

- **PRD §45** puts a coding question in the interview (Python, JavaScript, TypeScript, SQL); **§46** asks for a secure sandbox if code runs; **§47** lists eight criteria (correctness, test cases, edge cases, time and space complexity, code quality, readability, approach) and asks to store the final code, submissions, test results, execution time and memory; **§48** lists the console events to record and forbids unnecessary global keystrokes.
- The master plan's first design (§6.10, D9) ran every Run and Submit in a fresh hardened Docker container per run (`sandbox-runner`, four runner images, an escape suite). That is the platform's highest-risk component, the only one with Docker access, and it needs a managed sandbox in the cloud.
- **Product-owner decision, 2026-10-23:** no code execution and no sandbox. The candidate types the answer in a plain, notepad-like text box and submits it; the AI evaluates the code after the interview by reading it. The sandbox work started on the C6 branch was removed before anything was committed.

## Decision

- **What is dropped**, by that decision: code execution, the Run button, test cases (visible, hidden, edge and performance), measured runtime and memory, the `sandbox-runner` and its runner images, the escape suite, `coding-service` as a separate process, Monaco and IDE features on the desktop. §47's "test cases" criterion and "test results, execution time and memory" are not delivered; §46 applies to nothing because nothing runs.
- **Answers (`coding_submissions`, insert-only):** the code, its language (a label the candidate picks from the question's languages), size, SHA-256 and time, and its source: `submitted` (Submit), `time_limit` (the time ran out and the last saved draft was kept) or `closed` (the question ended another way: a spoken answer, the interview ending). The latest is the question's final code. Drafts stay in `workspace_snapshots` (`POST /workspace`). Code is capped at 256 KB.
- **Engine (§34):** `CodingController` keeps the coding state (the question, submissions, how it ended). The AI asks the question and tells the candidate to type the answer in the text box and press Submit. `Conductor.submit_code` is a turn: the submission and the closed question commit together, with no live analysis, and the interview moves on. A coding question that closes without a submission keeps the last draft as its final code in the same transaction. §91's `CODE_SUBMITTED` goes on the live stream; `CODE_RUN` is never sent.
- **Evaluation, inside C4's evaluator (ADR-0031):**
  - One strong-tier call per coding question (`evaluation.coding`, prompt `evaluation-coding-v1`, rubric `coding-v1`), alongside the answers' calls in the same run, with the same failure and retry rules.
  - Seven criteria from 0 to 10: correctness of the logic, approach, edge cases considered, time complexity, space complexity, code quality, readability. Complexity is the model's big-O estimate from reading and is labelled `estimated` everywhere it is shown.
  - Every criterion cites quotes that must be in the code: matched character for character, ignoring only spacing, and stored with their line numbers. A criterion without one is capped at 5 and flagged, as an answer's dimension is.
  - The question's score is the criteria's mean by fixed weights (correctness 30, approach 15, edge cases 15, code quality 15, time 10, readability 10, space 5); `rubric_version` is `coding-v1+w<digest>`. The prompt and rubric versions are pinned in the evaluation, and a pinned re-run reviews the code with them and reports the coding score's difference.
  - The code reaches the model as JSON data under a prompt that says so and that it was never run; an instruction in a comment is flagged (`manipulation_attempt`) and changes nothing. Empty code is not sent and scores 0 (`coding_not_answered`).
  - The coding score is the evaluation's coding entry, beside the overall score, not inside it; `EVALUATION_VERSION` is unchanged because the skills' and overall arithmetic is.
- **The gate:** a labelled coding set (`coding-eval-set-v1`, 18 submissions in Python, JavaScript and TypeScript: strong, partial, weak, comments only, an injection alone and an injection beside code) runs in `hv eval-interviews` with `coding_`-prefixed metrics, the same thresholds and baseline rule, and the same prompt lint. The mock grader reads the code's shape and follows the prompt as written, so removing any clause fails a coding metric.
- **Integrity telemetry (§48 subset):** typing started and stopped, paste, copy, cut, focus and blur from the text box only (`coding_telemetry`, insert-only); clipboard events carry a length and the schema has no column for text; no keystrokes. Reviewers see what the events add up to (pasted share of the final code, time away from the box, time typing) worded as signals, never proof.
- **Reports:** the coding report (question, final code, every submission, the review with its quotes and lines, the signals), the interview report's coding section, the internal candidate report, the Candidate 360 Coding tab and the review workspace's code panel. The candidate-visible draft mentions the review without numbers or signals.

## Consequences

- **Much less attack surface:** no candidate code runs anywhere, so there is no sandbox to escape, no Docker socket in the platform and no runner images to patch. The threat model's coding section is about prompt injection through code and the privacy of the console's events.
- **Weaker evidence of correctness:** the review reasons about the code; it can be wrong where running tests would not be. The UI says the code was never run and that complexity is estimated, the evidence is verified against the code, and a person decides. Real-model agreement is measured with `hv eval-interviews --live` once a vendor key works.
- **No editor help for the candidate:** small slips a compiler would catch are expected; the prompt says not to mark them down when the logic is clear.
- **PRD traceability:** Appendix A rows §45–§48 say what is delivered and what was removed by this decision. If execution is wanted later, it returns as a new decision with the sandbox design in the master plan's history (§6.10 before 2026-10-23).
- **Hand-offs:** B4 builds the console to `docs/api/contracts/coding.md` (no Monaco, no Run); SP-18 may deliver `CODE_SUBMITTED`; SP-21 may count coding scores; SP-22's retention covers the two new tables.
