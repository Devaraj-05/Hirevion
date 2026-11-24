---
version: 1
slug: "src-screens-interview-tsx"
primary_target: "src/screens/interview.tsx"
related_targets: ["src/screens/interview-stage.tsx"]
---

## Scope

The candidate desktop app's live interview screen (`InterviewScreen` and `InterviewStage`) and its End Interview confirmation. Visitor mode: **Operate**. Code-led build (Operate surface).

## Audience, task, constraints

- **Who and what:** a nervous candidate, alone, on a Windows laptop (1280×720 to 1920×1080), answering a recorded AI voice interview.
- **The task:** listen, answer, follow the time, and keep both cameras working.
- **States:** connecting, interviewer speaking, listening, candidate speaking, thinking, reconnecting, voice off (text mode), coding question open, design notes open, phone missing, low time (5 min and 2 min), sound blocked, notices, ending.
- **Constraints:** no new dependencies; CSS keyframes only; the system font stack; light and dark tokens; reduced motion, transparency and contrast; forced colours.

## Direction contract

THESIS: A quiet stage where the conversation is the interface. The interviewer is a living sphere that answers to real sound, and both voices are written down beside it. It refuses the video-call default of a grid of faces with a control bar of round icons.

OWN-WORLD: The ground is cool paper (`#f4f6f9`), with white panes of 20px radius on hairline borders (`#e1e5eb`) and ink at `#1d1d1f`. Blue (`#0068d6`) is the interviewer. One desaturated violet (`#6e5ce6`) is the candidate's own voice; focus rings stay blue. The orb is a pearl lit from the upper left, with soft concentric rings and no neon. The emblem is five rounded bars topped by a dot. End Interview is the only solid red. Figures are tabular, captions small and tracked in caps.

STORY: The candidate sees, at a glance, who is talking and what was said, how long is left, and that both cameras are live. They answer by voice, find the coding question on the left when it is asked, and end only through a confirmation that says it can't be undone.

FIRST VIEWPORT: A 56px solid bar (nothing scrolls under it). On the left, the emblem, "AI INTERVIEW", a hairline, then "{name} – {job} – Interview". On the right, the countdown and the red End interview button. Below it, three columns in a 1fr 1.15fr 0.85fr grid. The left column is an empty, quiet pane until a coding or notes question arrives. The centre holds an orb of up to 15rem (clamped to the window height) with its state label, and under it the transcript (Interviewer on the left, You on the right). The right column holds the main camera tile, the side camera tile, and a status row.

FORM: Pinned whole by the product owner (2026-11-22). seed: none (pinned): "Top Bar … Left Column - Coding Area … Center Column - AI Voice Interface … Right Column - Camera Monitoring … Apple-inspired … premium … minimalist".

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Memorable moment

The orb breathes with the interviewer's actual voice, and turns violet with the candidate's voice when they speak, while the transcript writes both of them in real time.

## Open decisions

None. The countdown comes from the agent's `remaining_seconds`. A local tick is kept, and a server value within 2 s of it is ignored, so the clock never jumps (no `deadline_at` change to the server).
