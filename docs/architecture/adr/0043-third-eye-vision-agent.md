# ADR-0043: A server vision agent watches the third eye for a second person and phones

- **Status:** Accepted
- **Date:** 2026-11-16
- **Sub-project:** C7-1 (SP-15b's third-eye analysis, the first part of C7)

## Context

- **PRD §53:** the second camera provides evidence about the candidate's posture, hands, a phone, an additional person, a secondary screen, the workspace and unusual movement. Signals are evidence, not proof. **§55** lists `PHONE_DETECTED` and `UNEXPECTED_PERSON_DETECTED`.
- Until now nothing looked at the phone's picture during the interview. It was recorded (ADR-0040) and checked only for placement before the start (ADR-0042).
- **Product-owner decisions, 2026-11-16:**
  - Watch for a second person and any phone.
  - Save a snapshot of each suspicious moment.
  - The detection runs on a server agent, not the candidate's laptop.
  - Any phone in view counts, not only one in the hand.
  - Flag, snapshot and warn the candidate.

## Decision

- **A worker of its own, `hirevion-vision`** (package `backend/vision_agent`), on LiveKit Agents like the interviewer:
  - The API dispatches it by name, beside the interviewer, when the interview has a third eye (`third_eye` not `off`) and proctoring isn't `off`.
  - It holds `hv:iv:{id}:vision` (core's `HeldKey`, now shared with the interviewer's lock), so a reconnect never sends a second one, and it stops when the interview ends.
  - It sets the participant attribute `hv.role=vision`, so the webhook doesn't take its leaving for the interviewer's.
- **What it watches:** only the phone's camera (`third-eye-*`, source camera), through `rtc.VideoStream` keeping the newest frame. Twice a second at most, one frame at a time, it runs MediaPipe's EfficientDet-Lite2 on the CPU in a thread (about 0.2 s a frame).
  - It is the desktop's placement model (ADR-0042), the same file checked by hash, keeping `person` and `cell phone`.
- **Rules** (`watch.py`, pure):
  - a second person is two or more people of score ≥ 0.5 and at least 2% of the picture, held 3 s;
  - a phone is any `cell phone` of score ≥ 0.4, held 2 s;
  - a missed frame (under 1 s) doesn't break a run;
  - an episode ends 5 s after the last sighting;
  - the same kind opens at most one episode a minute.
- **Recording:** the frame that started an episode is uploaded as JPEG to the interview's `evidence` folder. Then `ProctorEngine.detected` records a server event:
  - source `third_eye`, still ongoing;
  - the frame linked as `screenshot` evidence, origin `server`, with its SHA-256;
  - the third eye's recording window as usual.
  - The rules give both kinds CRITICAL (a phone at once, a second person after 3 s). The existing follow-ups then do the rest: the candidate's on-screen nudge, the AI interviewer's reminder at its next turn ("Please put any phones or other devices away" / "It looks like someone else may be with you…"), the recruiter's live alert, and snapshot requests to the desktop.
  - `detection_ended` closes the event with its length.
- **Dependency:** `mediapipe` (Apache-2.0), with its transitive OpenCV (contrib), matplotlib, sounddevice and others: about 150 MB, only in this worker's environment. They pass the licence gate.

## Consequences

- Nothing ends an interview: the recruiter judges the evidence (§53). A poster of a person, a phone-like object or a passer-by can raise an event. The thresholds are first settings.
- **C7-2** reports precision and recall on a labelled set and false positives per 45-minute session (SP-15b's exit), and adds the other §53 signals (posture, hands, secondary screen, unusual movement).
- Each watched interview costs the server about 0.4 of a CPU core. `HV_VISION_MAX_SESSIONS` (4) caps a worker's interviews.
- The cloud plan packages this worker as its own service. Locally, run it beside the interview agent (runbook).
- **Checked live (2026-11-16):** a scripted phone streamed a picture with two people into an interview's room. The agent was dispatched, joined, subscribed to the phone's camera only, saw the second person after 3 s, and stored the snapshot.
