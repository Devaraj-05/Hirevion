# ADR-0049: One attempt per interview: one reconnect within 2 minutes from the same laptop

- **Status:** Accepted
- **Date:** 2026-11-22
- **Sub-project:** C8-9 (interview session, candidate access, desktop app, recruiter web app)

## Context

The product owner's mock interview of 2026-11-21 ended on a thank-you page with "Back to your interviews". The owner, 2026-11-22: "candidate will able to again attend the interview. make sure candidate will only once attend the interview. Implement strict restrictions and secured interview slot. if candidate start the interview then closing in the middle of the interview and again attending the interview will not accepted."

What the code allowed:
- **The desktop:**
  - the thank-you page led back to the interviews list;
  - the list was never fetched again after sign-in, and it ignored each interview's status, so a submitted interview still offered "Get ready".
- **The server:**
  - `start` accepted `invited`, `in_progress` and `interrupted`;
  - the policy snapshot's resume rules were `{grace_seconds: 300, max_interruptions: 3, pause_timer: true}`, so a candidate could come back up to three times within 5 minutes each, with the clock paused, from any device;
  - the session-token check didn't look at the interview's status, so a cached token still passed the briefing, the system check and the consent for a finished interview (`start` refused it).

Asked about crashes and lost connections, the owner chose (2026-11-22): **one reconnect, within 2 minutes, from the same laptop; the clock keeps running; the recruiter sees it flagged; after that the interview ends and what was answered is evaluated.**

## Decision

### The rule, in one place

- `interview_session/attempts.attempt_of(interview, session_row, jkt, now)` decides what a candidate may do:
  - `available`: start;
  - `not_open`: wait for the window;
  - `reconnect`: rejoin, once;
  - `elsewhere`: another laptop started it;
  - `used`: taken, cancelled, or its reconnect is spent;
  - `expired`.
- The candidate's list, the session-token route, the preparation routes and `Conductor.start` all ask it.
- A taken interview is completed, evaluating, evaluated or abandoned.

### The policy

- New interviews get `resume = {grace_seconds: 120, max_interruptions: 1, pause_timer: false, same_device: true}`.
- A snapshot never changes (PRD §80): interviews assigned before keep their rules. `resume_policy()`'s defaults for missing keys are unchanged, and `same_device` defaults to false.

### The laptop

- The first start stores the session token's DPoP key thumbprint (`claims.jkt`) on `interview_sessions.device_jkt` (migration 0024).
- Under `same_device`, a start from any other key is refused: `409 interview-other-device`.

### The one reconnect

- A drop seen by LiveKit (`interrupt`) counts one interruption.
- The rejoin is `start` again from the same laptop, within 120 s. It may leave out the system check and the consent (the first start's stand), because the preparation page can't be redone in 2 minutes.
- A start while the interview is still `in_progress` (its answer was lost and the app asked again, or the app restarted before LiveKit saw the drop) is answered again and costs nothing. Only the drop LiveKit reports is counted. While the candidate is still in the room that start is refused with `409 interview-in-use` (`MediaControl.candidate_present`, as the LiveKit webhook already checks), so a second app can't join.
- A second drop completes the interview at once with the reason `left_early`. Both drops stay in the history.
- The open question is closed by the engine, and a coding draft becomes the final code, whether the second drop or the scheduler ends it.
- The scheduler completes an interview interrupted past its 120 s the same way (`end_left_early`, beside `abandon`). A completed interview is evaluated (the evaluation queues only for `completed`) and its transcript artifacts are written.
- The application moves to "interviewed", not back to the shortlist.
- Old-policy interviews are still abandoned and sent back to the shortlist.

### Refusals

| Situation | Answer |
|---|---|
| Completed, evaluating, evaluated or abandoned | `409 interview-already-taken` |
| The reconnect is spent or its window passed | `409 resume-limit-reached` |
| Another laptop | `409 interview-other-device` |
| Still in the room | `409 interview-in-use` |

They apply to `start`, the briefing, the system checks, the consents and the accommodations, so a cached session token never reopens a taken interview. The session-token route also refuses another laptop and a spent reconnect.

Heartbeats, proctoring events and recording uploads aren't refused: uploads continue after the end.

### The candidate's list

- Each interview carries `attempt` and, while interrupted, `reconnect_until`.
- A used attempt isn't listed, as a taken interview wasn't.

### The desktop

- **The thank-you page:** one button, **Close app**, which closes the window (`core:window:allow-destroy`). The flow has no way back from a submitted interview.
- **The interviews list:** fetched again from the server every time it shows (`profile`, which also restarts uploads a crash left behind). Each card's action comes from `attempt`: Get ready, Rejoin interview (with the time left), in progress on another device, or the countdown to the window.
- **Rejoining:** a Reconnect screen. It checks that the apps the interview forbids are closed, then calls `start` without the check and consent. It shows the time left as a guide (the laptop's clock may be off, so only the server says when it's too late), and keeps Rejoin offered after a passing refusal: a connection still closing, the phone, a busy service. Only a final refusal (taken, spent, another laptop, expired) says the interview has ended. It opens:
  - from the list;
  - straight after launch, when the saved session (the 8-hour refresh token, DPoP-bound to this laptop, ADR-0021) finds an interview to rejoin. The saved session is used only for this; otherwise the candidate signs in as before.
- **Closing the window during the interview:** asks first (the End Interview dialog). Confirming submits, so it ends the interview for good.

### The recruiter

- The interview page's Policy card shows "Attempts: one attempt · one reconnect within 2 min, from the same laptop".
- The history labels why an interview ended: the connection dropped and the candidate didn't rejoin, ended early by the candidate, the time ran out, or all questions asked.

## Consequences

- A candidate can't take an interview twice, from the app or by calling the API.
- A Wi-Fi drop or a crash costs at most the seconds lost. A second one ends the interview, and the answers given are still evaluated.
- The clock never stops. A candidate whose computer fails for longer than 2 minutes has a partial interview; the recruiter sees why, and decides (for example, by scheduling another interview).
- The desktop end-to-end test checks the thank-you page offers only Close app. The Reconnect screen's steps are tested as logic and through the Rust stub; a crash-and-rejoin run is part of the live check with the owner.
