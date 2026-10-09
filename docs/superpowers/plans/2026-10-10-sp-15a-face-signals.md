# SP-15a Computer vision core, desktop part — plan

- **Lane:** B (the local Windows PC).
- **Master plan:** §14 SP-15a, §6.12 (on-device MediaPipe at 5–10 fps; the severity table), §6.4 accommodations.
- **PRD:** §56 (the five face signals with temporal thresholds), §29 (system check), §101 (accommodations).
- **ADR:** ADR-0007 (MediaPipe in a module worker, GPU delegate with CPU fallback, measured cost).
- **Contract used:** `docs/api/contracts/proctoring.md` (the event shape and the proctor session's `thresholds` and `accommodations`).

**Goal:** the desktop's on-device face module, the temporal rule engine that turns its frames into
§56's signals and proctoring events, face-quality guidance for the system check, and the evaluation
harness for the exit criteria. The server-side `vision-agent` is a separate part of SP-15a (lane C).
SP-08b wires the module into the interview screen and forwards events to the native queue.

## Decisions

- **Code lives in `ai-interviewer-desktop/src/vision/`;** the spike (`src/spikes/media`) stays as it was, and what the module needs is copied from it.
- **Worker:** MediaPipe Tasks Vision `FaceDetector` (bundled BlazeFace short-range model) in a module worker, fed `ImageBitmap`s (scaled to at most 640 px wide) and skipping frames while busy.
  - GPU delegate first; the CPU delegate when GPU set-up fails or a GPU frame throws (once, then it stays on CPU).
  - The worker also draws each frame into a 32×24 canvas and measures its luminance (mean, standard deviation and edge energy) for obstruction and lighting.
  - The **face landmarker** (needed for gaze, SP-15b) isn't bundled yet: the five face signals need only boxes. The worker protocol keeps a `model` field so SP-15b can add it.
- **Per-frame observation:** `{ t, faces: [{ x, y, width, height, score }] (normalised, best first), frame: { meanLuma, stdLuma, edgeEnergy } }`. Nothing else leaves the worker: no pixels, no landmarks.
- **Per-frame classification** (with value hysteresis so a reading on the boundary doesn't flap):
  - `CAMERA_OBSTRUCTED`: no face, and the frame is near black (mean luma < 0.06) or flat (std < 0.03 and edge energy < 0.01). It takes precedence over `FACE_ABSENT`, so a covered lens raises one event, not two.
  - `FACE_ABSENT`: no face and not obstructed.
  - `MULTIPLE_FACES`: a second face scoring ≥ 0.6 (stays on at ≥ 0.5) and at least 5 % of the frame height.
  - `FACE_TOO_FAR` / `FACE_TOO_CLOSE`: one face, its box below 15 % / above 65 % of the frame height (2 points of hysteresis). Measured for a 16:9 webcam with a ~70° field of view: about 1.5 m and 35 cm.
  - "Face present" is the normal state and raises nothing.
- **Temporal rule engine (pure reducer plus a thin wrapper):**
  - Each signal is an episode tracker: idle → pending → active → idle.
  - **Gaps:** a gap shorter than `clear_after_ms` (1 s) doesn't end an episode, so a detector that misses one or two frames doesn't restart the clock and flapping input yields one episode, not many.
  - **Stale input:** when no frame arrives for `max_gap_ms` (2 s), open episodes end at the last frame, so a stalled worker never stretches an episode.
  - **Thresholds** are strict (`> 5 s`) and come from a config object:

    | Signal | Default | Source |
    |---|---|---|
    | `FACE_ABSENT` | warning > 5 s, critical > 30 s | §6.12 table |
    | `MULTIPLE_FACES` | critical > 3 s | §6.12 table |
    | `CAMERA_OBSTRUCTED` | critical > 5 s | §6.12 table |
    | `FACE_TOO_FAR` | warning > 10 s | this plan (no table row) |
    | `FACE_TOO_CLOSE` | warning > 10 s | this plan (no table row) |

  - The proctor session's `thresholds` (`{ "FACE_ABSENT": { "warn_after_ms", "critical_after_ms" } }`) override the defaults per signal.
  - **Accommodations** are a registry of config transforms keyed by the contract's kinds. `relaxed_gaze` covers face distance too (§6.4: "relaxed gaze/face-distance rules"): it widens the distance bounds (10 % / 75 %) and doubles their durations. It never relaxes absence, multiple faces or obstruction. Unknown kinds are ignored, so SP-15b adds gaze rules without changing callers.
- **Events** follow `proctoring.md` without `seq` (the native queue assigns it): `event`, `source: "camera"`, `started_at` (server time through an injected clock), `duration_ms`, `confidence`, `evidence: []` and `details`.
  - An episode yields up to three events with the same `event` and `started_at`: `phase: "started"` when it crosses its first threshold, `"escalated"` when it crosses critical, and `"ended"` with the final duration. `details.level` is `warning` or `critical`: the threshold the client crossed. The server still decides severity.
  - `confidence` = the share of the episode's frames where the condition held × the mean per-frame confidence (1 for absence and obstruction; the second face's score; the face's score for distance), to two decimals.
  - `details` holds only numbers (frames, max faces, mean face height, mean luma): no images, no biometric templates.
- **Adaptive frame rate (CPU budget):** a pure controller keeps an EWMA of inference time and holds the worker's busy time under 150 ms per second (15 % of one core), between 5 and 10 fps. Over budget, it drops at once to the fastest rate that fits; under 70 % of budget at the next rate, it climbs by 1 fps after 5 s. It reports `over_budget` when even 5 fps doesn't fit. Measured frames per second and inference p50/p95 are exposed for the heartbeat's `vision_fps`.
- **System-check guidance (`src/checks/face.ts`):** the module samples about 2 s of frames; `assessFace` reports issues found in at least half of them, in priority order: obstructed, no face, multiple faces, too dark (mean luma < 0.25), too far, too close, off centre (centre more than 25 % of the frame away).
  - **Choice: it folds into the existing `camera` check** rather than adding a new check name, since the upload's names are fixed by the contract and the screen's labels. The issues become the `camera` result's `detail` (from the `vision.guidance` messages).
  - Obstructed, no face and multiple faces turn a passing camera into `warn` (the camera is mandatory, so the candidate fixes it and checks again); lighting, distance and centring are advice only. The blocking set is a parameter, so a policy can make it all advisory.
- **Strings:** a new top-level `vision` namespace in `en-IN.json` and `en-US.json` (same keys).
- **Evaluation harness (exit criterion "precision/recall on labelled clips"):**
  - A labelled timeline is the module's observations for a clip plus ground-truth intervals per signal, as a human marks them (`{ signal, start_ms, end_ms }`).
  - A label counts as reportable when it lasts longer than the signal's first threshold plus a 500 ms tolerance. Labels within ±500 ms of the threshold are "don't care". Predicted episodes are matched one-to-one to labels by overlap. Precision and recall are then computed per signal.
  - Targets proposed for CP2: precision ≥ 0.90 and recall ≥ 0.90 for `FACE_ABSENT` and `MULTIPLE_FACES`.
  - A seeded synthetic set (detector misses, spurious second faces, frame jitter, short and long episodes) runs in CI today.
  - **Real clips plug in later:** record with consent (or use a licence-compatible public set), label intervals, play each clip through a `<video>` element into `startFaceModule({ onObservation })`, and save `{ version: 1, clip, observations, labels }` as JSON in `src/vision/eval/clips/`. The clip test picks up every file there automatically. The files hold boxes and luminance numbers only, never video.

## Tasks

1. This plan.
2. Pure maths, tests first: frame statistics and obstruction; per-frame classification; the config, policy overrides and accommodations.
3. The temporal engine, tests first: 4 s absent → nothing; 6 s → warning with its duration; 31 s → critical; two faces for 2 s → nothing; 3.5 s → `MULTIPLE_FACES`; flapping doesn't spam; stale input; contract shape.
4. The frame-rate controller and the evaluation harness with the synthetic set, tests first.
5. The worker and the main-thread module (tested with a fake worker and fake timers; no real webcam).
6. `checks/face.ts` and the `vision` strings, tests first.
7. Typecheck, tests and Biome.

## For SP-08b

```ts
const face = await startFaceModule({
  source: videoFrameSource(videoElement),
  config: visionConfigFromPolicy(session),             // thresholds + accommodations
  toServerIso: (t) => clock.serverIso(t),                // from interview-session clock sync
  onEvent: (event) => void invoke("proctoring_enqueue", { event }), // the native queue adds seq
  onStats: (stats) => (heartbeat.vision_fps = stats.fps),
});
// on pause, break or end:
face.stop(); // ends open episodes ("ended" events), then terminates the worker
```

## Not in this part

- Gaze, pose, hands, phone and objects (SP-15b), and the landmarker model they need.
- Evidence snapshots for face events (the evidence manager, SP-14 / SP-15b).
- The `vision-agent` server verification (lane C).
- Re-measuring CPU with a real webcam (needs the candidate's or developer's consent; ADR-0007 follow-up).
