# ADR-0042: The third eye's placement check: the desktop shows the phone's picture and turns green only with the candidate and the whole laptop in view

- **Status:** Accepted
- **Date:** 2026-11-15
- **Sub-project:** C8-3 (third eye: phone page, API, desktop)

## Context

- **PRD §30:** "Follow third-eye placement instructions."
- Until now, the desktop showed only text guidance and the phone's status (ADR-0040). Nobody checked what the phone actually filmed before the interview.
- **Product-owner decisions, 2026-11-15:**
  - The desktop shows the phone's footage.
  - The candidate is asked whether the phone is placed well, and "green" appears only when both the candidate and the laptop keyboard are clearly visible. Then the candidate can move on.
  - The phone offers its front camera as well.
  - Chosen options: automatic detection plus the candidate's confirmation; strict, with no way past without green; a switch button on the phone.

## Decision

- **The phone page:**
  - It opens on the rear camera and has a "Use the front camera" / "Use the back camera" button.
  - `LocalVideoTrack.restartTrack` changes the camera without republishing, so the pairing stays `connected` and the recording goes on.
- **The preview:**
  - `POST /third-eye/pairings/{id}/preview` gives the desktop a LiveKit token that is hidden, subscribe-only, for one room, and lives ten minutes at most.
  - It is issued only for the caller's interview and its current, connected pairing, and only before the start or while the interview is paused.
  - Rust fetches it with the session token and DPoP; the webview joins and attaches only the phone's camera.
- **The check (on the device):**
  - A worker runs MediaPipe's EfficientDet-Lite2 (int8, Apache-2.0, bundled in `public/models`) on the CPU twice a second on the phone's picture, keeping only `person`, `laptop` and `keyboard`. Pixels never leave the desktop.
  - The picture is green with a person (score ≥ 0.5) and a laptop, or failing that a keyboard (score ≥ 0.4), wholly inside the picture, at least 1% of the side from the edges. The person may reach the edges: a candidate near the phone fills the picture.
  - First-try findings (2026-11-16): the GPU delegate loaded but returned no detections (the owner's laptop, and headless Chromium), so the check runs on the CPU (about 0.3 s a frame on an i5). Lite0 scored a laptop seen from the side 0.13, Lite2 0.6–0.7, so the desktop bundles Lite2 (7.5 MB).
  - A picture taller than wide is never green. An upright phone can't fit the candidate and the laptop together, and a web page can't make it film landscape. The desktop and the phone page both say to turn the phone sideways (owner's first preview, 2026-11-15).
  - Green must hold for 3 s; it drops after 1 s without.
  - The preview draws both boxes: green when inside the picture, amber when cut off. A status line says what to fix.
- **Strict gate:**
  - Continue is enabled only when the picture is green and the candidate ticks "My phone shows me and my whole laptop, keyboard included".
  - Continue first records the placement (`POST /third-eye/pairings/{id}/placement` → interview event `third_eye_placement_confirmed`, with the scores), so the recruiter sees it.
  - There is no fallback. An optional third eye can still be skipped before a phone connects.

## Consequences

- A candidate whose room the detector can't read (dark, unusual laptop, cluttered desk) can't continue. Support has to help, or the recruiter waives the third eye (`third_eye_waiver`).
- The check runs on the client. A modified desktop could skip it, but release builds are integrity-checked (ADR-0019), and the recorded scores, the phone's recording and proctoring remain the evidence. Nothing here is proof on its own (§53).
- The scores and the 0.5 / 0.4 / 1% / 3 s values are first settings. Tune them on real rooms, with the C7 vision work.
- The preview token can watch every track in the room. Before the start, the room holds only the phone, and the token is refused once the interview runs.
