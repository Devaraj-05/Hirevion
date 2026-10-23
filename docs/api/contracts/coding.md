# Contract: the coding console (desktop ↔ API)

- **Provider:** lane C (SP-16, C6). **Consumer:** lane B (B4 builds the console).
- **Decision:** [ADR-0033](../../architecture/adr/0033-coding-answers-without-execution.md). By product-owner decision (2026-10-23) the coding question is answered in a plain, notepad-like text box. **Nothing is executed:** there is no Run, no test cases, no sandbox and no measured runtime or memory. The code is reviewed by the AI after the interview, by reading it.
- **Conventions:** as in [README.md](README.md): `/api/v1`, RFC 9457 errors (branch on `code`), the interview-session token with a fresh DPoP proof on every call, the clock from `GET /time`.

## How the console works

1. The AI reaches the coding question. `hv.state` (and `GET /interviews/{id}/session`) show it with `"workspace": "code"` and its `languages`; the AI says to type the answer in the text box, choose its language and press Submit.
2. The desktop opens the console: a monospace text box (no IDE features are needed), a language picker with the question's `languages` (a label only), the question's text and its time left, and a Submit button.
3. While the candidate types, the desktop saves a draft with `POST /interviews/{id}/workspace` (`kind: "code"`; interview-session.md), at most every few seconds and on blur. After a restart it restores the draft from `GET /interviews/{id}/coding`.
4. It sends the console's integrity events in batches (`POST …/coding/telemetry`).
5. Submit sends the code once (`POST …/coding/submissions`). The question closes and the interview moves on; the answer carries the next state. There is no second submission.
6. When the question's time runs out (or the interview ends) before Submit, the server keeps the last saved draft as the final code. The desktop should save the draft just before the limit.

## `GET /interviews/{id}/coding`

The open coding question, or `{"question": null}` when the open question isn't one.

```json
{
  "question": {
    "question_id": "uuid",
    "text": "Write a function solve(nums, target) that …",
    "languages": ["python", "javascript"],
    "starter_code": { "python": "def solve(nums, target):\n    pass\n" },
    "time_limit_seconds": 600,
    "asked_at": "2026-10-23T10:00:00Z",
    "draft": { "language": "python", "content": "def solve(…", "saved_at": "…" }
  }
}
```

- `languages`: some of `python`, `javascript`, `typescript`, `sql`, as the question allows.
- `starter_code`: the recruiter's starting text per language (may be empty). Put it in the box when the candidate picks a language and the box is empty.
- `draft`: the last text saved with `POST /workspace`, or `null`.

## `POST /interviews/{id}/coding/submissions`

- **Body:** `{ "question_id": "uuid", "language": "python", "code": "…" }` (no other fields).
- **`202`:**

```json
{
  "submission": {
    "id": "uuid", "question_id": "uuid", "language": "python", "size": 412,
    "sha256": "…", "source": "submitted", "submitted_at": "…"
  },
  "state": { "…": "as in interview-session.md; in text mode it holds the next question" }
}
```

- **Errors:**
  - `409 question-not-current` (it isn't the open question, or it was already submitted);
  - `409 not-a-coding-question`;
  - `422 language-not-offered` (not one of the question's `languages`);
  - `413 code-too-large` (over 256 KB of UTF-8);
  - `409 interview-not-in-progress`;
  - `429` past 10 submissions a minute per interview.

## `POST /interviews/{id}/coding/telemetry`

- **Body:** `{ "question_id": "uuid", "events": [ { "kind": "paste", "at": "…", "chars": 120 } ] }`, 1 to 200 events.
- **Kinds (PRD §48, the console only):** `typing_started`, `typing_stopped`, `paste`, `copy`, `cut`, `focus`, `blur`.
  - `paste`, `copy` and `cut` carry `chars`, the length of the text. **Never send the text**; any other field is refused.
  - The other kinds carry no `chars`.
  - Typing started is the first key after a pause of about two seconds; typing stopped is that pause. **Never send keystrokes**, and nothing outside the text box.
- **`202`:** `{ "accepted": 3 }`.
- **Errors:** `422 unknown-event` or a validation error for an unknown kind or field, `422 invalid-chars`, `422 event-out-of-time` (an `at` before the question was asked or after now, beyond two minutes either way), `422 too-many-events`, `404 question-not-found`, `409 not-a-coding-question`, `409 interview-not-in-progress`, `429` past 60 batches a minute.
- Queue events while offline and send them after reconnecting, as for proctoring.

## What the server does with them

- Every submission and every kept draft is stored with its SHA-256 (`coding_submissions`); the latest is the question's final code. Events go to `coding_telemetry`.
- §91's `CODE_SUBMITTED` (question, submission, language, length) goes on the interview's live stream.
- After the interview, the evaluation reviews the final code on seven criteria with quotes from the code, and recruiters see the code, every submission, the review and the integrity signals (reviewers read the signals as signals, never proof).

## Changes

- 2026-10-23: written by lane C (C6, SP-16) after the product owner's decision: a notepad-style console, no execution. Replaces the Monaco, Run and test-case plan; interview-session.md's "coding runs and submissions belong to SP-16's own contract" now points here.
