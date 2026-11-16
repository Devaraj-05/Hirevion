# C7-1 Third-eye vision agent: a second person and phones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** during the interview, the server watches the phone camera's picture and flags a second person or any phone in view. Each flag carries a saved snapshot, and the candidate is warned (product owner, 2026-11-16; PRD §53, §55; master plan SP-15b).

**Architecture:**
- **The vision agent.** A new LiveKit Agents worker, `hirevion-vision`, is dispatched by the API when an interview with a third eye starts.
  - It joins the room unseen and subscribes only to the phone's camera.
  - It checks two frames a second with the same EfficientDet-Lite2 model as the desktop's placement check, in a thread, on the CPU.
  - Pure rules turn detections into episodes: a second person held 3 s, a phone held 2 s.
- **Recording an episode.** It goes through the proctoring engine like any other event (`UNEXPECTED_PERSON_DETECTED`, `PHONE_DETECTED`, source `third_eye`), with:
  - a JPEG snapshot of that frame, stored as server evidence;
  - the existing third-eye recording window.
- **The warning.** The engine's existing nudges put a notice on the candidate's screen. The AI interviewer says the reminder at its next turn: "It looks like someone else may be with you…" or "Please put any phones or other devices away."

**Tech stack:** LiveKit Agents 1.8 (as the interview agent), `mediapipe` Tasks for Python (Apache-2.0, **new dependency**), Pillow (installed), the core's proctoring engine and storage.

## Global constraints

- **Product-owner decisions, 2026-11-16:**
  - a server agent, not the candidate's laptop;
  - any phone in view, not only in the hand;
  - flag, snapshot and warn.
- **Evidence, never proof (§53):** nothing ends the interview; the recruiter judges.
- **Privacy:**
  - Frames are analysed in memory; only an episode's snapshot is stored, under the organisation's prefix, with the SHA-256 and the usual evidence audit.
  - The notice (§83) already names the third eye.
- **Load:** one detection at a time per interview (frames are skipped, never queued), at most 2 frames a second, so about 0.3 s of CPU per frame. The interview agent's voice process is untouched.
- **Data:** synthetic data only; tests use fixed detections, not photos of people.
- **Process:** TDD; no Claude attribution.

## Tasks

### Task 1: Rules: `hirevion_vision_agent.watch` (pure)
- Input: one frame's detections (label, score, box) and its time.
- **Count, per frame:**
  - people with score ≥ 0.5 and a box of at least 2% of the picture, so a poster or a far reflection is ignored;
  - phones (`cell phone`) with score ≥ 0.4.
- **Episodes:**
  - A second person starts when two or more people are held for 3 s; a phone when one is held for 2 s.
  - An episode ends after 5 s without.
  - The same kind opens at most one episode a minute.
- Output: `Started(kind, at, frame_index)` and `Ended(kind, at)`.
- Tests: held vs flicker, the end, the one-a-minute limit, a small far person ignored, phone and person together.

### Task 2: Detector adapter: `hirevion_vision_agent.detector`
- MediaPipe `ObjectDetector` in IMAGE mode on the CPU, keeping only `person` and `cell phone`.
- The model is bundled in `backend/vision_agent/models/` with its source, licence and SHA-256. It is the file the desktop uses, checked by hash.
- Tests:
  - frames are converted from LiveKit's `VideoFrame` (RGBA) for the detector;
  - the adapter maps MediaPipe's result to detections;
  - a missing model fails at start with a clear message.

### Task 3: Server evidence: `ProctorEngine.detected(...)`
- A server event with a snapshot:
  - normalised and stored like a desktop event (severity, escalation, nudges, the AI reminder);
  - the snapshot JPEG uploaded to `{org}/interviews/{id}/proctoring/snapshots/{event_id}.jpg` and linked as evidence `snapshot`, origin `server`, with its SHA-256, plus the existing `third_eye_segment` window;
  - an ended episode closes the event with its duration.
- Policy defaults: both kinds from the third eye are CRITICAL and nudge, so the candidate hears the reminder. Organisations can lower them as for other events.
- Tests (DB): the event stored with severity and evidence, the snapshot in storage, the nudge delivered, duplicates for the same episode ignored.

### Task 4: The worker: `hirevion_vision_agent.agent` and its dispatch
- Joins as a hidden agent; subscribes only to `third-eye-*` camera tracks, and again after the phone rejoins.
- Samples frames with `rtc.VideoStream`; runs the detector in a thread; feeds the rules; on `Started` encodes that frame and calls `detected`.
- Leaves when the interview ends.
- Dispatch: `MediaControl.dispatch_vision`, called with the interviewer's dispatch when the policy's third eye isn't `off` and proctoring isn't `off`.
- Tests: the dispatch (FakeMedia); the job's frame loop with a fake stream and detector (one detection in flight, frames skipped).

### Task 5: Docs, review, live check
- ADR-0043: a server vision agent for the third eye.
- Threat-model rows: the agent's token and stored snapshots.
- Runbook: how to run the worker locally.
- PENDING_TASKS (C7-1) and STATUS.
- `/code-review`; merge.
- Live check (the owner): during a test interview, a second person steps into the phone's view, then a phone is shown. Expected: two CRITICAL events with snapshots on the live dashboard and in the report, a notice on the candidate's screen, and the AI's reminder at its next turn.

## Exit criteria

- Rule, adapter, engine and dispatch tests are green.
- The owner's live check shows both events with snapshots and the warning.
- C7's remaining exit (precision and recall on a labelled set, false positives per 45-minute session) stays open for C7-2.
