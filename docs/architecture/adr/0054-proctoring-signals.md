# ADR-0054: The other proctoring signals, both cameras correlated, and their scores

- **Status:** Accepted
- **Date:** 2026-11-26
- **Sub-project:** C7-2 and B4b-3 (SP-15b: advanced proctoring)
- **Request:** the product owner, 2026-11-26: "improve proctoring".

## Context

- C7-1 (ADR-0043) watched the third eye for a second person and a phone only. PRD §53 lists seven third-eye signals: posture, hands, phone, additional person, secondary screen, workspace and unusual movement.
- The desktop's camera (SP-15a) had only the five face signals (§56). It had no gaze (§57) and didn't look for a phone.
- Master plan §6.12 also asks for:
  - correlation of the two cameras;
  - detection of additional speakers;
  - §59's speech measures, of which C8-7 shipped all but repetition and prosody.
- SP-15b's exit criterion asks for three things:
  - each detector's precision and recall on a labelled set;
  - false positives per 45-minute session within budget;
  - no signal shown as proof.

## Decision

### The third eye (server vision agent)

- **Five new server events.** The vision agent raises them from the third eye (`client=False`, so a device can't send them). Each goes through the server's rules like any other event:

  | Event | What it means | Policy check | Default weight |
  |---|---|---|---|
  | `SECONDARY_SCREEN_DETECTED` | a second screen besides the candidate's own (any two monitors, TVs or laptops), held 5 s | `displays` | warning |
  | `CANDIDATE_LEFT_VIEW` | nobody in a readable picture, held 10 s (counted only once the candidate has been seen) | `face` | warning, critical from 60 s |
  | `HANDS_OUT_OF_VIEW` | neither wrist visible, held 15 s | `third_eye` | warning |
  | `UNUSUAL_MOVEMENT` | large frame-to-frame change, held 4 s | `third_eye` | warning |
  | `THIRD_EYE_VIEW_CHANGED` | the phone moved, turned away or covered, held 5 s | always on while the third eye is on | warning |

- **Weight while it lasts:**
  - Each hold reaches its warning tier, so an episode is a warning when it is first recorded and alerts live.
  - While it stays open, the agent tells the server how long it has lasted every 10 s (`ProctorEngine.detection_progress`). A candidate away for a minute becomes critical then, not only once they are back.
  - A later regrade keeps what backed the event before (`both-cameras`).

- **How each signal is measured:**
  - **Screens:** EfficientDet-Lite2 now also keeps `laptop` and `tv`, each with a score of at least 0.5 and at least 1% of the picture.
    - Overlapping boxes count as one screen.
    - One screen is the candidate's own: a laptop, or a desktop PC's monitor, which COCO calls `tv`.
    - A laptop with an allowed external monitor therefore shows as one open episode, beside the desktop's own `EXTERNAL_DISPLAY_CHANGE`.
  - **Scene (`scene.py`):** works on a 64×36 grey thumbnail held in memory only.
    - Motion is the mean absolute change between two looks, flagged at 0.06 or more.
    - The view is compared with the first still picture by normalised cross-correlation, which ignores lighting; below 0.5 the view has changed.
    - A flat picture (a covered lens or a dark room) is a changed view and is never readable, so it is never taken for the candidate leaving.
    - After 30 s a new readable view becomes the reference, so one move is flagged once.
  - **Hands (`pose.py`):** MediaPipe Pose Landmarker Lite (Apache-2.0, bundled and pinned by hash). Only the wrists' visibility is read. It runs at most once a second, and only when someone is in the picture.
- **Hold share and gaps:** a run must show the condition in at least 70% of its looks, not only last its hold. In the evaluation, two short false sightings one frame apart were most of the phone's false positives. A run tolerates a gap of 1 s, or 15% of its hold if longer: two missed looks in a row cost hands (held 15 s) a fifth of their episodes.
- **Recorded details:** only numbers are recorded: screens counted, motion, view match, whether hands were visible. The snapshot of the frame that started the episode stays the evidence, as in C7-1.

### Both cameras correlated (core rules)

- An event from one camera carries the ids of the other camera's matching events within 10 s, in `details.server.corroborated_by`, with the reason `both-cameras`. The report reads this as "seen by both cameras". The matching pairs are:
  - `MULTIPLE_FACES` ↔ `UNEXPECTED_PERSON_DETECTED`;
  - `PHONE_DETECTED` ↔ `PHONE_DETECTED`;
  - `FACE_ABSENT` ↔ `CANDIDATE_LEFT_VIEW`.
- It changes no weight: two detectors agreeing is stronger evidence, but still not proof.

### The desktop camera (B4b-3)

- **Gaze (§57):**
  - **Reading:** in the face worker, MediaPipe's face landmarker (bundled `face_landmarker.task`, Apache-2.0) runs at most about 7 times a second, only with exactly one face. It turns landmarks and ARKit eye blendshapes into four numbers: head yaw, head pitch, eyes left/right and eyes down/up. Landmarks never leave the worker.
  - **Direction:** judged against this candidate's resting pose (the median of the first 40 readings, about 10 s), because a webcam above the screen makes looking at the screen a slight downward look. Hysteresis is applied when coming back. The result is left, right, down or centre.
  - **Event:** `GAZE_DEVIATION` uses the engine's existing smoothing and thresholds. It warns from 10 s by default, gets no critical level (the server caps it anyway) and carries the main `direction`. It runs only when the session's policy checks `gaze`.
- **The face module comes first:**
  - A landmarker that can't load turns gaze off, and only says so after `ready`. An error before `ready` would have stopped the face module.
  - A landmarker that throws turns gaze off without costing the face result its frame.
- **A phone on the main camera:** the existing object worker (EfficientDet-Lite2) runs in its own worker once a second, for `cell phone` only, so it never holds up face detection. It is used only when the policy checks `phone`.
  - The face module reads the latest score while it is fresh (1.5 s).
  - `PHONE_DETECTED` from the camera needs a score of 0.5 held 2 s. The camera keeps a 2 s floor even though the server's tier says critical at once.
- **Nudges:** both signals have nudge texts in en-IN and en-US.

### A second voice and repetition (§59)

- **Second voice:**
  - The interviewer agent turns on Deepgram's diarisation (`HV_STT_DIARIZE`, on by default).
  - The candidate's voice is the label with the most words over the first 20 words, not merely the first label heard, which could be the interviewer's voice leaking back.
  - Another label raises `ADDITIONAL_SPEAKER_DETECTED`, an audio server event, only when it persists: at least 2 transcripts and 8 words within a minute, and at most once a minute. Streaming diarisation can split one voice for a moment.
  - It records only the number of voices and words, never the words.
  - The core's `ProctorEngine.detected` now takes the event's source, and accepts each server-raised event only from its own source.
- **Repetition:** the interview analytics add `repeated_phrases`: three-word phrases said at least three times within one answer segment, the top five. A chain of overlapping windows of one longer phrase counts once. The web analytics panel shows them as a signal.

### Scores (exit criterion)

- **Third eye:** `uv run python -m hirevion_vision_agent.evaluation`. Seeded sessions at 2 looks a second, with modelled detector errors (missed sightings and short bursts of false ones per signal): 30 ten-minute labelled sessions per signal, and 10 clean 45-minute sessions for false positives. The budget is at most 1 false episode per 45 minutes per signal, and 2 for all signals together.

  | Signal | Precision | Recall | False positives per 45 min |
  |---|---|---|---|
  | phone | 1.000 | 0.994 | 0.7 |
  | second person | 1.000 | 1.000 | 0.1 |
  | secondary screen | 1.000 | 0.993 | 0.0 |
  | candidate out of view | 1.000 | 1.000 | 0.0 |
  | hands out of view | 1.000 | 1.000 | 0.0 |
  | unusual movement | 1.000 | 1.000 | 0.0 |
  | view changed | 1.000 | 1.000 | 0.0 |

  Episodes are matched to labels by overlap, as the desktop's harness does: an episode that a false sighting started a moment early is still the labelled one.

- **Desktop camera:** the SP-15a harness's synthetic set now includes gaze and phone clips. Across seeds 1, 7, 42 and 2026, every signal has precision and recall of 1.00 on its reportable episodes. That set is small: two reportable gaze and two phone episodes per seed.
- **What these numbers measure:** the temporal rules on modelled detector error, not the detectors on real rooms. Detector accuracy needs the owner's labelled recordings of real rooms and phones (STATUS "Found in testing").
- **Not proof:** every new label in the report and the recruiter app reads as what was seen ("Hands out of the side camera's view"), never as misconduct. The proctoring report keeps its "no single score for cheating" note.

## Consequences

- PRD §53's seven third-eye signals, §57's gaze, §58's "hands below frame" and "repeated downward movement" (as `down` gaze episodes), §59's repetition and additional speakers, and §6.12's cross-camera correlation are built.
- **Left open (STATUS):**
  - **Real rooms:** a labelled set of real rooms for detector accuracy, and the owner's check that gaze left/right/down match a real face (the signs are unit-tested on synthetic landmarks).
  - **Not built:**
    - §58's typing posture and unusual hand movement correlated with editor telemetry;
    - §59's prosody, which needs audio analysis of the recording;
    - the server re-checking the device's critical events, with `CLIENT_INTEGRITY_WARNING` on disagreement.
  - **Possible false second voices:**
    - echo of the interviewer's voice if the laptop's echo cancellation fails;
    - Deepgram restarting its speaker numbering on a reconnect.
- **CPU:**
  - The vision agent adds the pose model, at 1 look a second only with someone in view.
  - The desktop adds the landmarker (only with gaze checked) and one object look a second (only with phone checked).
  - The adaptive frame rate (SP-15a) still keeps the face module within its budget.
