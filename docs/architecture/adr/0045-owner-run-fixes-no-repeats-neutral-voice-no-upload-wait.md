# ADR-0045: No repeated questions, a neutral and warned interview, a warm interviewer, and no wait after submitting

- **Status:** Accepted
- **Date:** 2026-11-21
- **Sub-project:** C8-5 (interview engine, interview agent, desktop app)

## Context

The product owner took a spoken interview on the desktop app on 2026-11-21 (C8-2). The run's
transcript, logs and database showed:

- **The same question, again and again.**
  - The interview asked "What would you use Redis for in a web application?" ten times, and a Python question twice.
  - The development library held 13 copies of each simulator question, because every seeded interview inserted the library again.
  - The planner took each copy (its own id) for a new question.
- **"Right." after a correct answer.** It was one of the agent's four filler acknowledgements ("Mm-hm.", "Okay.", "Right.", "I see."), and it told the candidate the answer was right.
- **The voice broke up at the start.**
  - In dev mode LiveKit keeps no job runner waiting, and on Windows a job runs as a thread of the agent's process.
  - The interview's runner was made only when the job came. Its setup timed out after LiveKit's 10 s, so the agent joined 18 s late.
  - The next runner loaded the database driver and configured the ORM on the event loop during the greeting. The loop stalled for up to 1.7 s, and voice activity detection ran up to 4.5 s behind.
- **The thank-you page made the candidate wait.**
  - It showed "0% uploaded. 228 parts still to go. Please don't close the app yet."
  - Nothing had uploaded during the interview: the signed URLs pointed at `https://storage.hirevion.localhost`, which this PC's Caddy doesn't publish. That was a fault in the local run's setup.
  - The same gap made the server raise `SCREEN_CAPTURE_STOPPED`, and the AI said the screen was no longer shared.
- **The owner's decisions:**
  - the candidate never waits after submitting;
  - the system check shows only the camera, microphone, network and display;
  - a firm warning against cheating;
  - the phone step's text must never overflow (a long tunnel link pushed it out of its card).

## Decision

### Questions are never repeated

- A question's text is compared with case, spacing and the closing mark ignored (`planner.said`).
- The planner's pool keeps one question per text: a library copy is left out once a usable copy is in, so a copy the filters turn away (another skill, type or language) never hides one.
- A pool question whose text the interview has asked is never picked, nor counted as a fresh question for an extra one. This also protects a checkpoint saved before the fix.
- The simulator's seed inserts its library and its coding question once per organisation.

### The interviewer stays neutral and warns once

- **Acknowledgements:**
  - While an answer is analysed, the interviewer says "Thank you.", "Okay, thank you.", "Thanks." or "Noted.".
  - It says one only after an answer. A request ("repeat that", "I need a moment") or silence gets none, since the engine replies at once. The same classifier as the engine's decides.
  - A test keeps words that judge an answer ("right", "correct", "good", "great"…) out of both the agent's and the engine's acknowledgements.
- **The spoken warning:** the greeting says "Please note that this interview is monitored and recorded, as described in the terms you agreed to. Any outside help, other device or AI tool will be reported to the hiring team."
- **The written warning:** the Terms step shows it above the agreement: "This interview is monitored and recorded, as the Terms and Conditions below describe. Using another app, device, person or AI tool is reported to the hiring team, who may end your application."
- **Why neither warning names a device:** what is recorded (the screen, the phone…) depends on the interview's policy, and the terms list it.
- **The closing line:**
  - It no longer asks the candidate to keep the app open, and it doesn't say they can close it either: the desktop is still finishing while it plays.
  - The thank-you page says the app can be closed.

### The interviewer is ready before the interview

`hirevion_interview_agent.warm`:
- one runner always waits ready in dev mode (LiveKit keeps none). Production keeps LiveKit's default of one per CPU;
- a runner has 60 s to get ready (a busy laptop needs more than 10 s);
- the prewarm loads the voice activity model, the database driver, and the ORM's configured mappers, so the first query loads nothing on the event loop;
- with the turn detector in use, it also loads huggingface_hub's download module, which the detector reads its language list with as the session starts (0.3 s on the loop as the greeting began).

### No wait after submitting

- The thank-you page shows only that the interview has been submitted and can be closed. The upload progress view, its strings and the `upload_progress` command are gone.
- Nothing is lost:
  - answers and proctoring events are saved as they happen;
  - the recording uploads during the interview (PRD §50);
  - what is left keeps uploading while the app is open, and otherwise at the next launch (§51; the segments stay encrypted on disk).
- The local runbook now says to start the API with `STORAGE_PUBLIC_ENDPOINT=http://127.0.0.1:10000/<account>` when Caddy can't publish 443, so a local run uploads during the interview.

### What the candidate sees of the system check

- The system check shows the camera, the microphone, the network and the display.
- Every other check still runs and is still sent to the server. It shows only when it failed, because then the candidate has something to fix.

### The phone step fits

- The placement column can no longer be widened by its content.
- The link wraps in full, since a candidate may have to type it.

## Consequences

- An interview can run out of bank questions sooner. Generated questions then fill in, and an extra question is added only for a skill with an unasked one.
- The first job of a fresh agent no longer waits for a runner. Live check on this PC:
  - over three voice benches, the job started 0.1–0.3 s after the request and the agent joined within a second;
  - once the agent was in the room, no event-loop stall reached 300 ms. One of 387 ms remains before it joins (reading files), when nothing is spoken yet;
  - speech detection kept real time;
  - it measured 1.4–2.0 s from the end of an answer to the AI's voice.
- A candidate who closes the app at once leaves the last parts for the next launch. If they never open the app again, those seconds of recording are missing. This was already true of a crash (§51).
- The Playwright review now:
  - checks for text cut off inside a card;
  - covers the owner's 1920×1005 window;
  - uses a link as long as a real tunnel link.
  On the old phone step it reports the overflow the owner saw.

### Not yet done

These are the next part (C8-6):
- a "close other apps" check before Start, listing the running apps the blocked-apps policy forbids;
- saving the full list of running processes when the interview starts.

Today only the processes that match the policy are saved, as `BLOCKED_PROCESS_DETECTED`.
