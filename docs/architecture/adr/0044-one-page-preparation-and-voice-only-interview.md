# ADR-0044: One page before the interview, a voice-only interview screen, and interviews that last their set time

- **Status:** Accepted
- **Date:** 2026-11-16
- **Sub-project:** C8-4 (desktop app, interview engine, phone page, third-eye check)

## Context

The product owner's spoken try on 2026-11-16 found these problems:

- **The AI was never heard.** The agent spoke (Deepgram `aura-2-thalia-en`), but the desktop never played it. LiveKit hands a subscribed audio track to the app, which must attach it to an audio element, and the interview screen never did.
- **The interview screen was cluttered.** It showed:
  - the question's text and number;
  - a typed-answer box;
  - four control buttons;
  - raw notice codes ("Please check: camera_covered");
  - a services banner.
- **The owner's decisions for the interview screen:**
  - show only the interviewer's words, while it speaks, at most 250 characters, moving up as it goes on;
  - no buttons other than an Exit Interview at the top right;
  - no answer box;
  - the window fills the screen and never overflows.
- **An interview with a 30-minute window ended early.** It stopped after the template's planned question count. The owner's decision: the interview asks questions until its time is up, then submits.
- **Five separate screens came before the interview:** the briefing, the system check, consent, the phone, and Ready. The owner's decision: one page, in this order:
  1. camera and microphone access;
  2. the system check;
  3. the Terms and Conditions;
  4. the phone.
- **The phone page looked basic.** The owner wants it professional, with professional instructions.
- **A second laptop went unnoticed.** On the owner's picture, the green-zone check judged only the highest-scoring laptop. The detector scored the other laptop 0.41 and the candidate's own 0.33.
- **Dark mode never applied.** The app set a `.dark` class, but the design system switches its tokens on `data-theme`.

## Decision

### Hearing the interviewer

- The room joins with `autoSubscribe: false` and subscribes to audio tracks only. The phone's video is no longer downloaded back to the laptop.
- `playInterviewerAudio` (`src/interview/audio.ts`) attaches each audio track to a hidden element as it arrives, and removes it when it goes.
- It also subscribes to the audio already in the room once the join completes. The interviewer usually joins first, and joining fires no `trackPublished` for tracks already there.
- If the webview's autoplay policy blocks sound, a "Turn on sound" notice calls `room.startAudio()`.

### The interview screen

- **Layout:**
  - It fills the whole window: a bar, then the stage.
  - The bar shows:
    - the connection, which is the secure session;
    - the time left, red for the last two minutes;
    - quiet indicators for the camera, the microphone, the screen and the phone, which are PRD §32's status strip (`src/interview/health.ts`, from the services' problem reports and the phone watcher);
    - Exit Interview at the top right.
  - Exit asks once, then submits.
- **The interviewer's presence and words:**
  - The interviewer is a sphere that breathes with its state (speaking, listening or thinking).
  - While it speaks, its words show as they are spoken: the last 250 characters, starting at a whole word (`src/interview/captions.ts`).
  - The candidate's own transcription is never shown.
  - Afterwards the words go, by the owner's decision ("when the bot speaks then only display the transcript, afterwards not"). PRD §101 asks for captions; it is met while the interviewer speaks. A candidate who missed the words says "repeat the question", which speaks and captions it again. The text-answers accommodation keeps the question in view throughout.
- **What was removed, and how its function remains:**
  - The question card and the question number are gone.
  - The control buttons are gone. Speech covers them: the engine already understands "repeat that" and "I need a moment", and turn detection ends an answer.
- **Where typing remains:**
  - A coding question opens its console beside the stage (ADR-0033), and a design question opens its notes pad (ADR-0041).
  - Typed answers remain only where speech can't be used: an approved text-answers accommodation, or a voice connection that failed.
- **Notices:**
  - Notices float at the bottom, out of the way.
  - A proctoring reminder shows the engine's own sentence, never its code, and leaves after 12 seconds. It shows once per nudge (its id), though every state message repeats it.
- **Time-up fallback:**
  - If the clock reaches zero and the server hasn't closed the interview within 30 seconds, the app asks the server for the time left, and submits only if there is none.
  - It never fires while the room reconnects, because the server may pause the clock and give the time back.
- **Debug-only gallery:** `#/gallery?state=…` shows the stage in each state, for review and Playwright.

### Interviews that last their set time

- **A floor, not a cap:** the planned question count is now a floor. `TimeController.extend` adds one more main question when three things hold:
  - every planned question has been asked;
  - the time left beyond the closing reserve (150 seconds) and any coding question still to come is at least 90 seconds. While a coding question is still to come, it must be a whole question's time (180 seconds), so the coding question keeps all of its own;
  - the skill can take more: the one asked least for its weight, required skills first, never a dropped skill, and only one that still has a question this interview hasn't asked.
- **How it ends:** final questions and the close still come, and the clock's `time_up` still ends an overrunning answer.
- **Bank questions stay near the target level:** a bank question is taken only at the target level or one either side. Otherwise a generated question at the level is used, so an easy question never follows a hard one just because the bank ran out.
- **No repeats:** a generated question is one this interview hasn't asked yet: the target level first, then the nearest. A skill with nothing new to ask gets no more extra questions.

### One page before the interview

- **The flow:** interviews → prepare → interview → completed.
- **The prepare page:**
  - It shows four numbered steps beside the company's instructions and the interview's role and length.
  - Each step opens when the one before it is done. Done steps fold to one line.
  - **The steps** (step logic in `src/prepare/steps.ts`):
    - **Camera and microphone:** an "Allow access" button, a live picture and a level meter.
    - **The system check:** starts by itself.
    - **One Terms and Conditions checkbox:** ticking it records the consent.
    - **The phone:** the QR code beside its placement steps, then the green-zone picture and the confirmation.
- **The Start bar:** a floating bar holds "Start interview", enabled once every step is done. The page's scroll area keeps whatever is scrolled into view above the bar (scroll padding), and what appears in the open step comes into view above it.
- **Robustness:**
  - The camera and microphone are let go if the candidate leaves while Windows asks for them.
  - A system check that fails to run offers "Check again" instead of stalling.
- **A server-required phone:** if the server asks for a phone the briefing didn't, the phone step opens again.

### The phone page

The phone page has the desktop's calm look, in light or dark following the phone:
- a brand line, then the company and role;
- a top-view placement diagram;
- five placement steps with icons;
- a full-width "Start camera" button pinned to the bottom.

While live, it shows a preview, the status ("Live. The interview can see this camera."), the camera switch, and the connection numbers folded under "Connection details".

### Someone or something else in the phone's picture

- **The candidate's laptop:** the green-zone check takes the laptop nearest the candidate, from 0.3. A faint one of their own is never "another" laptop; it counts as seen from 0.4, as before (ADR-0042).
- **What counts as extra:**
  - any other laptop at 0.3 or more. Laptop boxes that overlap by 30% or more, or that hold each other's centre, are one laptop (lid and base);
  - any other person at 0.5 or more who covers at least 2% of the picture. Person boxes are one person only when they overlap by half or more, because someone standing right behind a candidate who fills the picture has their centre inside the candidate's box.
- **Effect:** extras are drawn in red. The picture can't turn green while there is one, and the status line asks for them to leave.

### Dark mode

`useDarkTheme` sets `data-theme`, so Windows' dark setting now applies to every screen.

## Consequences

- **Fewer screens, fewer clicks:** two screens and one Start replace five screens and many clicks.
- **The PRD's §26 steps all remain:** the briefing, the system check, consent, the third eye, and the start gate.
- **Interviews run their full length:** a 30-minute interview takes about 30 minutes, so evaluation sees more answers. Recruiters who set a question count now set a minimum.
- **Generated questions without expected concepts score on the heuristic when live analysis falls back.** The engine tests now check the ladder's climb on the planned questions only.
- **The second-laptop rule is a first setting.** It may flag a laptop seen twice that doesn't overlap enough, so it needs the owner's real-room check together with C8-3's thresholds.
- **Verification so far:**
  - Unit tests for captions, audio, health, steps, framing and verdict, and for the engine and conductor.
  - The desktop e2e on the new flow, and the phone e2e streaming to the local LiveKit.
  - A Playwright pass over every desktop page at 800×600, 1280×672 and 1920×1080, in light and dark, checked for overflow.
- **Not yet verified:** hearing the AI is unit-tested, but not yet heard in the owner's spoken run (C8-2).
