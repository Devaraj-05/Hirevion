# B4a: the desktop coding console — implementation plan

**Goal:** Build the desktop's coding console for SP-16 (ADR-0033, `docs/api/contracts/coding.md`), following the product owner's 2026-11-14 decision: B4 starts with the console alone. The candidate types code into a plain text box, every draft is saved, and Submit sends it once. Nothing is ever run.

**Architecture:**
- Rust gains three interview actions: `coding` (GET), `coding_submit` (POST `coding/submissions`) and `coding_telemetry` (POST `coding/telemetry`). Like the other actions, the webview only names the action, and Rust adds the session token and DPoP (ADR-0018).
- The stub backend gains a coding question so the console can be developed and tested end to end without an API.
- The console's logic is in `src/interview/coding.ts`, plain TypeScript tested with Vitest:
  - the draft saver: at most one save every 5 s, a save on blur, and a save just before the time limit;
  - the integrity events: typing started and stopped after a 2 s pause, paste, copy and cut sending lengths only, and focus and blur. They are sent in batches of up to 200, and queued and retried while offline;
  - the starter code;
  - the question's clock, corrected by the server offset from `GET /time`;
  - the 256 KB limit.
- `src/screens/coding-console.tsx` is the screen. The interview screen shows it in place of the text-answer box when the question's `workspace` is `code`.

**Global constraints:**
- Never send keystrokes or clipboard text.
- Nothing is executed.
- The language is a label chosen from the question's `languages`.
- One Submit per question.
- Wording: plain, active sentences, in both `en-US` and `en-IN`.
- No new dependencies.

## Tasks

- [x] **1. Rust actions and stub.**
  - Tests: each new action maps to its contract route.
  - Tests for the stub: it serves the coding question with its starter code and saved draft, keeps drafts sent with `kind: "code"`, takes one submission and moves on, refuses a second submission (`question-not-current`) and a language the question doesn't offer, and counts telemetry events.
- [x] **2. Command wrappers** in `commands.ts`, with the coding types.
- [x] **3. Console logic** (`coding.ts`), tested with fake timers:
  - the draft saver's timing, its retries and its flush;
  - when typing counts as started and stopped;
  - the clipboard lengths and that no text is ever sent;
  - batching, and requeueing after a failure;
  - when starter code is swapped in;
  - the question's time left and the size limit.
- [x] **4. The console screen** and its wiring into the interview screen. It shows a "Saved at …" status, a hint that Tab indents (press Esc, then Tab, to leave the box), and a confirmation before the one Submit. It handles `question-not-current` by refreshing the session, and handles `language-not-offered`, `code-too-large` and network errors. Strings go into both locales.
- [x] **5. End-to-end test.** After "Ready", `e2e/desktop.e2e.mjs` starts the interview, answers the first question, types code into the console, waits for the save, submits and sees the next question.
- [x] **6. Documentation.**
  - In PENDING_TASKS, split B4: B4a (the console) is done, and B4b keeps the whiteboard, snapshot requests, third-eye status and SP-15b.
  - Update STATUS and MASTER Appendix A rows §32, §45 and §48.
  - Add the desktop notes to the threat model's SP-16 section.

## Verification

- `cargo test -q` (desktop app crate).
- `pnpm --filter @hirevion/ai-interviewer-desktop exec vitest run`, then typecheck and Biome.
- `pnpm --filter @hirevion/ai-interviewer-desktop e2e`.
