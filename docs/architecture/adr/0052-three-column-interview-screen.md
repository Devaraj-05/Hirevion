# ADR-0052: The interview screen in three columns, with both voices written live and both cameras shown

- **Status:** Accepted
- **Date:** 2026-11-24
- **Sub-project:** C8-12 (candidate desktop app, third-eye phone page)
- **Supersedes:** ADR-0044's voice-only interview screen (its single-page preparation and set-length interviews stand)

## Context

The product owner's review of 2026-11-22 asked for a new interview screen, "Apple-inspired", "premium" and "minimalist":
- **Top bar:** "{name} – {job} – Interview", a countdown, and End Interview with a confirmation.
- **Three columns:** a coding area that stays empty until a coding question is asked; the AI voice orb with a live transcript of both the AI and the candidate; and the main camera with the third-eye camera, each labelled, with a live indicator and a "CONFIDENTIAL • INTERVIEW SESSION" watermark.
- **Branding:** an original waveform emblem with the "AI INTERVIEW" wordmark.
- **Skills:** the owner required four design skills: apple-design, ui-ux-pro-max, design-taste-frontend-v1 and impeccable.

ADR-0044's screen showed only the interviewer's words, at most 250 characters, while it spoke. The candidate's own transcript was dropped, and so was the phone's video (audio-only subscription).

## Decision

- **Layout:**
  - a 56 px translucent bar, then a three-column grid (1fr / 1.15fr / 0.85fr);
  - the coding column widens to 1.4fr / 1fr / 0.8fr while a coding or design question is open, and the grid moves rather than jumps;
  - below 1024 px the coding area takes a full-width row above the interviewer and the cameras, and below 768 px everything stacks;
  - the timer and End interview never leave the bar.
- **The orb:**
  - a pearl sphere: blue for the interviewer, violet for the candidate, both softened toward pearl;
  - it moves with the real sound: Web Audio analysers on the interviewer's remote track and the local microphone write a `--level` CSS variable every frame, outside React's render (`levels.ts`: RMS with a noise floor, critically damped following, and hysteresis for "you're speaking");
  - states: speaking, listening (a still halo), candidate, thinking and connecting (a slow rim light), voice off, and resting. Each state's name is also written under the orb.
- **Transcript:**
  - LiveKit `lk.transcription` streams, merged by `lk.segment_id`; an interim line is replaced by its final one, and never the other way round (`transcript.ts`);
  - the candidate is recognised by identity or by `lk.transcribed_track_id`;
  - the interviewer is on the left and "You" on the right; interim words are lighter;
  - it follows new lines and offers "Jump to latest" when scrolled back;
  - screen readers hear final lines only.
- **Cameras:**
  - **Main camera:** the published local track, mirrored.
  - **Side camera:** the phone's camera, subscribed on the interview's own connection at `VideoQuality.LOW`. The phone page now publishes with simulcast and a 180p layer, so the laptop downloads a few hundred kbps; the recorder and the vision agent keep the 720p layer.
  - **Text mode:** shows the camera the app opens itself.
  - **On every tile:** a label, a status with a dot and words, and the watermark along the bottom edge. The watermark is a UI overlay only, so the recorded tracks stay clean.
  - **Status row:** microphone, screen and secure session (PRD §32), each in words as well as colour.
- **End interview:**
  - a solid red button that opens a dialog: "End the interview?" / "You can't come back to it…";
  - "Continue interview" takes the focus;
  - the same dialog opens when the window is closed (C8-9).
- **Countdown:**
  - amber at 5 minutes and red at 2;
  - a screen-reader announcement at 5 minutes and at 1;
  - the local tick is kept unless the agent's time differs by more than 2 seconds, so the clock no longer jumps every refresh (no server change; the plan's `deadline_at` wasn't needed).
- **Notices:** between the orb and the transcript, never over the newest words.
- **Look:** the app's Apple-like tokens are refined rather than replaced:
  - a cool ground `#f4f6f9`, hairline `#e1e5eb`, and white panes of 20 px radius;
  - one violet `#6e5ce6` (dark `#a598ff`) for the candidate's voice only;
  - End interview `--danger-solid`;
  - the Windows system font, and lucide icons (no new dependencies).
- **Accessibility:**
  - `prefers-reduced-motion`: the orb holds still, and there are no entrance animations or rim light;
  - `prefers-reduced-transparency`: solid chips;
  - `prefers-contrast: more`: ink borders;
  - `forced-colors`: the orb becomes a system-colour ring.
- **Design record:**
  - `ai-interviewer-desktop/PRODUCT.md` (confirmed by the owner);
  - the direction contract in `.impeccable/surfaces/`;
  - `DESIGN.md`, written from the built screen.

## Consequences

- **Laptop download:** the laptop now downloads the phone's low layer for the whole interview.
- **Phone upload:** the phone's upload grows by that layer, about 150–300 kbps.
- **Spoken run:** the owner's spoken run is the check of the live transcript's timing on real Deepgram segments and of the orb's response to real audio. The unit tests cover merging, levels and states, and the desktop e2e (text mode, no LiveKit) covers the layout and the dialog.
- **Gallery:** `#/gallery?state=…` (debug builds) shows every state with synthetic data and canvas-drawn camera feeds for review.
