# ADR-0041: A plain-text notes pad for design questions, instead of a whiteboard

- **Status:** Accepted
- **Date:** 2026-11-15
- **Sub-project:** SP-16 (B4b-2; desktop, engine and evaluation)

## Context

- **PRD §32:** "For non-coding questions, the coding panel becomes an appropriate interview workspace."
- The master plan read this as an Excalidraw whiteboard for system-design questions, with "its snapshot" going into the evaluation (§6, workspace interpretation). None of it was built. The engine gave every question other than coding the workspace `none`, and the evaluation read no snapshot.
- The product owner had already replaced the coding IDE with a notepad-like console (ADR-0033).
- **Product-owner decision, 2026-11-15:** a notes pad, chosen over Excalidraw and over no workspace.

## Decision

- **Which questions.** A `system_design` question opens the existing `whiteboard` workspace (`engine.planner.WORKSPACES`). Coding keeps its console; every other question has none. The wire value stays `whiteboard`, so the contracts and the `workspace_snapshots` check are unchanged; on the desktop it is a notes pad.
- **The desktop pad** (`src/screens/notes-pad.tsx`):
  - plain monospace text, for the parts, the data flow, simple text diagrams and trade-offs;
  - saved with `POST /interviews/{id}/workspace` (`kind: "whiteboard"`, `language: null`) at most every 30 s while typing, on blur, and once more when the question closes;
  - the same draft saver and "Saved at" status as the coding console;
  - unsaved text from the pad and the coding console is saved before the interview ends;
  - it opens on the last saved notes (`GET /interviews/{id}/workspace/{question_id}`). A follow-up of a design question starts from its parent's notes, and the pad stays read-only until they load, so a new save never hides earlier notes.
- **The answer is unchanged:** it is still spoken, or typed in the answer box, and the question closes the usual way. There is no Submit and no integrity telemetry for the pad.
- **What the AI says:** when it asks a design question, it says once that the notes pad is there and is read with the answer (`phrasing.DESIGN_NOTES`).
- **Evaluation:**
  - The latest notes snapshot of a question whose workspace is `whiteboard` reaches its request as `design_notes`, capped at 8,000 characters. Notes saved against any other question are ignored. The field appears only when notes exist, so every other question's request and input digest stay the same.
  - Manipulation phrases in the notes flag the question `manipulation_attempt`, as in an answer.
  - Prompt `evaluation-question-v2` adds one sentence: weigh the notes with the answer, but take quotes only from `answer_turns`.
  - v1 stays for pinned re-runs. The eval gate passes on v2, and its baseline records v2.

## Consequences

- **Small and reviewable:** no new library and no drawing format to judge. The notes are text the model reads as data, under the same no-instructions clause as the answer.
- **Not quoted:** a score supported only by the notes, with nothing in the spoken answer, is still capped as unsupported. This is deliberate, because the evidence links to the recording.
- **Visible to reviewers:** the interview report's Answers section shows each design question's notes, captioned as weighed but never quoted. The timeline lists each save under the transcript source as "Design notes saved for question N".
- **PRD traceability:** Appendix A row 32 points here. An Excalidraw whiteboard would need a new decision.
