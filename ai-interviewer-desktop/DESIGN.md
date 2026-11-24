---
name: Hirevion Candidate App
description: A calm, light desktop app for taking a timed, recorded AI voice interview.
colors:
  cool-paper: "#f4f6f9"
  ink: "#1d1d1f"
  surface: "#ffffff"
  surface-muted: "#eef1f5"
  surface-sunken: "#e6e9ef"
  hairline: "#e1e5eb"
  field-stroke: "#c7c7cc"
  muted-ink: "#63636a"
  interviewer-blue: "#0068d6"
  interviewer-blue-hover: "#0058b8"
  blue-wash: "#e6f1fd"
  blue-wash-ink: "#004a99"
  candidate-violet: "#6e5ce6"
  violet-wash: "#f1effd"
  orb-blue: "#4f86e8"
  orb-violet: "#7b6de0"
  orb-pearl: "#eef3ff"
  success: "#1b7438"
  success-wash: "#e7f6ec"
  warning: "#8a5300"
  warning-wash: "#fff4dc"
  danger: "#b3261e"
  danger-wash: "#fdecea"
  end-red: "#c9241c"
  camera-black: "#15171c"
  dark-ground: "#0e0e10"
  dark-ink: "#f5f5f7"
  dark-surface: "#1c1c1e"
  dark-surface-muted: "#2a2a2d"
  dark-hairline: "#38383b"
  dark-muted-ink: "#a6a6ad"
  dark-interviewer-blue: "#409cff"
  dark-candidate-violet: "#a598ff"
  dark-violet-wash: "#221d3d"
  dark-blue-wash: "#0c2743"
typography:
  display:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "2rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.1rem"
    fontWeight: 600
    lineHeight: 1.375
    letterSpacing: "-0.02em"
  bar-title:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 500
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  transcript:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.5
  question:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 600
    letterSpacing: "0.02em"
  clock:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 600
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  wordmark:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.14em"
rounded:
  field: "12px"
  bubble: "14px"
  tile: "16px"
  pane: "20px"
  pill: "9999px"
spacing:
  hair: "6px"
  xs: "0.5rem"
  sm: "0.9rem"
  md: "1rem"
  lg: "1.25rem"
  xl: "2rem"
components:
  button-primary:
    backgroundColor: "{colors.interviewer-blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    height: "2.5rem"
    padding: "0 1.25rem"
  button-primary-hover:
    backgroundColor: "{colors.interviewer-blue-hover}"
  button-primary-stage:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.cool-paper}"
    rounded: "{rounded.pill}"
    height: "2.5rem"
    padding: "0 1.25rem"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    height: "2.5rem"
    padding: "0 1.25rem"
  button-quiet:
    textColor: "{colors.interviewer-blue}"
    rounded: "{rounded.pill}"
    height: "2.5rem"
    padding: "0 1.25rem"
  button-end-interview:
    backgroundColor: "{colors.end-red}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    height: "2.25rem"
    padding: "0 1rem"
  pane:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.pane}"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    height: "2.75rem"
    padding: "0 0.875rem"
  status-pill:
    backgroundColor: "{colors.success-wash}"
    textColor: "{colors.success}"
    rounded: "{rounded.pill}"
    height: "1.75rem"
    padding: "0 0.75rem"
  notice:
    backgroundColor: "{colors.warning-wash}"
    textColor: "{colors.warning}"
    rounded: "{rounded.tile}"
    padding: "0.75rem 1rem"
  transcript-line:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.ink}"
    typography: "{typography.transcript}"
    rounded: "{rounded.bubble}"
    padding: "0.5rem 0.8rem"
  transcript-line-interviewer-active:
    backgroundColor: "{colors.blue-wash}"
  transcript-line-candidate-active:
    backgroundColor: "{colors.violet-wash}"
  camera-tile:
    backgroundColor: "{colors.camera-black}"
    rounded: "{rounded.tile}"
  camera-chip:
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    height: "1.6rem"
    padding: "0 0.6rem"
---

# Design System: Hirevion Candidate App

## Overview

**Creative North Star: "The Quiet Stage"**

The candidate app is a calm room in which the conversation is the interface. A cool paper ground carries white panes on hairline borders, and almost everything is ink and grey. Colour is spent on meaning, not decoration: blue for the interviewer, a desaturated violet for the candidate's own voice, red only for ending, and green, amber and red dots for live state. The interviewer is not a face or an avatar but a pearl sphere of light that answers to the real sound, and both voices are written down beside it.

The system is Apple-inspired in its restraint (the owner's binding direction): the system font, soft radii, pill buttons that press in at once, shallow shadows, and motion on a single long-tail ease that settles rather than bounces. It is dense enough for a working interview on a 1280 by 720 laptop and never scrolls the window; a screen's own content scrolls when it must.

It refuses the video-call default: no grid of faces, no floating bar of round icon controls. Every state is said in words as well as colour.

**Key Characteristics:**
- Cool paper ground, white 20px panes, hairline borders, ink text.
- Colour carries a speaker or a state, never decoration.
- A light, breathing orb as the interviewer's only presence.
- The system font, tabular figures for time, tracked capitals only in the mark.
- Light and dark themes from one token set; every system preference is honoured.

## Colors

A near-monochrome cool grey world with two speaker hues and one destructive red, each kept to its job.

### Primary
- **Interviewer Blue** (`interviewer-blue`): the app's accent outside the interview (primary pill buttons, quiet links) and, on the interview stage, the interviewer's colour: the speaking label, the interviewer's active transcript line (on Blue Wash with Blue Wash Ink), and every focus ring. Dark theme: `dark-interviewer-blue`.
- **Blue Wash / Blue Wash Ink** (`blue-wash`, `blue-wash-ink`): the soft tint and its readable text for the interviewer's line and accent status pills.

### Secondary
- **Candidate Violet** (`candidate-violet`, `violet-wash`): the candidate's own voice and nothing else: the "You're speaking" label, the candidate's active transcript line, and the orb when it turns to the candidate. Dark theme: `dark-candidate-violet`, `dark-violet-wash`.

### Tertiary
- **Orb Light** (`orb-blue`, `orb-violet`, `orb-pearl`): the three lights mixed in OKLab inside the orb only. The interviewer's orb is blue softened toward pearl; the candidate's is violet softened toward pearl. Never used as flat fills elsewhere.
- **End Red** (`end-red`): the one solid red, on End interview and its confirmation.

### Neutral
- **Cool Paper** (`cool-paper`): the window ground.
- **Surface White** (`surface`): panes, panels, the top bar, fields.
- **Muted Surface / Sunken Surface** (`surface-muted`, `surface-sunken`): resting transcript lines, inset blocks in the preparation steps, neutral pills.
- **Hairline** (`hairline`): pane and panel borders, the divider in the top bar. **Field Stroke** (`field-stroke`) edges inputs.
- **Ink / Muted Ink** (`ink`, `muted-ink`): text and secondary text (pane titles, speaker names, "left", empty states). Ink also fills the stage's action buttons.
- **Camera Black** (`camera-black`): behind camera feeds and their empty states.
- **Status** (`success`, `warning`, `danger` with their washes): live dots, status pills, notices, the clock at low and critical time.

### Named Rules
**The Two Voices Rule.** Blue is the interviewer, violet is the candidate. Violet appears only where the candidate is speaking or has just spoken; it never marks a button, a link, a focus ring or a status.

**The Ink Action Rule.** Inside the interview stage, action buttons are ink on paper, never blue, so blue keeps meaning "the interviewer". Outside the stage, the primary button is Interviewer Blue.

**The One Red Rule.** End interview is the only solid red on any screen. Danger text and washes say a problem; solid red says "this ends it".

**The Words Too Rule.** Every status dot sits beside the words for its state. Colour is never the only signal.

## Typography

**Display Font:** Segoe UI Variable Text (with Segoe UI, system-ui, -apple-system, sans-serif)
**Body Font:** the same system stack
**Label/Mono Font:** the same stack; figures use tabular numerals

**Character:** One native Windows face at a 15px root, set quietly: headings tightened to -0.02em and balanced, body at 1.5 line height, weight doing the hierarchy rather than size.

### Hierarchy
- **Display** (600, 2rem, 1.25): the page heading on the interviews list and the preparation screen.
- **Headline** (600, 1.75rem, 1.25): a screen title with its one line of lead (max 60ch).
- **Title** (600, 1.1 to 1.2rem): step headings and interview cards. The top bar's interview name is **Bar Title** (500, 0.95rem, -0.01em), truncated on one line.
- **Body** (400, 1rem, 1.5): prose and leads. **Transcript** (0.95rem, 1.5) in bubbles capped at 60ch; **Question** (1.05rem, 1.55, max 70ch) for the coding prompt.
- **Label** (600, 0.72 to 0.8rem, 0.02em): pane titles, speaker names, camera chips, live labels. Sentence case, muted ink.
- **Clock** (600, 1.15rem, tabular): the countdown, followed by a muted "left".
- **Wordmark** (600, 11px, 0.14em, uppercase): "AI INTERVIEW" beside the emblem, and the camera watermark (9.5px, 0.16em). These are the only tracked capitals.

### Named Rules
**The Figures Hold Still Rule.** Time and codes use tabular numerals so a ticking clock never shifts its neighbours.

**The Mark Owns the Caps Rule.** Uppercase tracking belongs to the wordmark and the confidential watermark. Section labels and captions are sentence case.

## Layout

The window is a fixed frame that never scrolls; each screen scrolls its own content. The interview stage is a 56px top bar over a three-column grid (coding, interviewer, cameras) at `1fr 1.15fr 0.85fr`, with 1.25rem gaps and padding. When a coding or notes question opens, the grid eases to `1.4fr 1fr 0.8fr` over 420ms and the orb shrinks with it; nothing jumps.

The centre column stacks the orb and its label, any notices (always between the orb and the transcript, never over the newest words), the transcript, and the typed-answer pane when text mode is on. The right column is a flex column of 4:3 camera tiles that give up height before their status row does, cropping the picture rather than squashing it.

Breakpoints step down without changing the idea: at 1279px gaps tighten to 1rem; at 1023px the stage becomes two columns and the coding area takes the top row (or the left when open, with a 4.5rem orb beside it); at 767px everything is one column and the cameras sit side by side. The window's minimum is 800 by 600.

Spacing runs on a small rhythm: 0.5rem inside chips and between lines, 0.9 to 1rem between stacked parts, 1.25rem for pane padding and grid gutters, 2rem for empty states.

## Elevation & Depth

Mostly flat, with depth from tone (paper, white, muted) and hairlines. Two shadows exist, both soft and neutral. Camera tiles and the floating "jump to latest" pill sit one step higher than panes; the coding pane drops its shadow and half its opacity while idle. The top bar has no ruled line; a 12px fade of ink at 5% marks its lower edge.

### Shadow Vocabulary
- **Rest** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.04)`): panes on the stage, secondary buttons.
- **Lift** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.04), 0 12px 32px rgb(0 0 0 / 0.07)`): panels on the other screens, camera tiles, floating pills. Dark theme raises both to 0.4 and 0.45 alpha.
- **Orb glow** (`0 26px 60px -30px` in the orb's own light, plus a 1px inner white rim): the orb only.

### Named Rules
**The Light Not Neon Rule.** The orb is lit pearl: colours mixed toward `orb-pearl`, a highlight from the upper left, rings that widen with real sound. No saturated glows, no pulsing on a timer when nobody speaks.

## Shapes

Soft, consistent corners that tighten as elements get smaller: 20px for panes, panels and dialogs; 16px for camera tiles, the status row, notices and inset blocks; 14px for transcript bubbles; 12px for fields; full pills for every button, status pill, chip and the live dot. The orb is a perfect circle with up to two concentric hairline rings. The emblem is five rounded bars on a 24-unit grid with a dot over the centre bar, drawn in ink on surfaces and in translucent white over video.

## Components

### Buttons
Pills that press in at once.
- **Shape:** full pill (9999px), 2.5rem tall (3rem large), medium weight.
- **Primary:** Interviewer Blue with white text, hover to the deeper blue. On the interview stage the same button is ink with paper text, hover to 84% ink.
- **Secondary:** white surface, hairline border, rest shadow. **Quiet:** blue text, blue-wash on hover.
- **End interview:** End Red pill, 2.25rem tall, 600 weight, a phone-off icon, 12% darker on hover; it always opens a confirmation where Continue is the focused, safe choice.
- **Press / Focus:** scale to 0.97 on press (off under reduced motion); a 2px focus ring in the ring blue with 2px offset.

### Chips and Status
- **Status pill:** 1.75rem pill, the state's wash with its text colour, a 6px dot, a few words.
- **Camera chip:** a translucent dark pill (`rgb(18 20 26 / 0.5)`, 12px blur) over video for the camera's name and its live state; opaque under reduced transparency.
- **Status row:** a 16px bordered list under the cameras: icon, name, dot and the state in words.

### Cards / Containers
- **Corner Style:** 20px.
- **Background:** white surface on cool paper.
- **Shadow Strategy:** Rest on the stage, Lift elsewhere (see Elevation).
- **Border:** 1px hairline (70% on the other screens' panels).
- **Internal Padding:** 1.25rem; pane headers 0.9rem 1.25rem 0.5rem with a muted Label title.

### Inputs / Fields
- **Style:** white field, Field Stroke border, 12px radius, 2.75rem tall on sign-in (the kit field is 2.25rem).
- **Focus:** the blue focus ring.
- **Error / Disabled:** danger border; 50% opacity.

### Notices
Something the candidate should know, said once: a 16px-radius block in a status wash and its text colour, 0.9rem, faded in. On the stage they sit centred under the orb, at most 34rem wide.

### Voice Orb (signature)
The interviewer's presence. A pearl sphere (clamp 9rem to 15rem; smaller when coding opens) whose scale, inner light and rings follow the live audio level. Speaking: two rings widening with sound. Candidate speaking: the light turns violet. Listening: one still hairline halo. Thinking, connecting, reconnecting: a slow light travelling round the rim (2.6s), with the orb desaturated while not connected. Its state is always written in the label beneath it. In Windows High Contrast it becomes a system-coloured ring.

### Live Transcript (signature)
Interviewer on the left, the candidate ("You") on the right, each line a 14px muted bubble under a small speaker name. Only the line being spoken carries its speaker's colour; earlier lines go quiet, and words still being heard are muted ink until final. New lines rise 6px and fade in over 260ms.

### Camera Tile
A 4:3, 16px-radius tile on Camera Black with the Lift shadow. The main camera is mirrored. A name chip top left, a live chip top right, and the emblem with "CONFIDENTIAL • INTERVIEW SESSION" faint along the bottom edge, drawn over the picture only.

## Do's and Don'ts

### Do:
- **Do** keep blue for the interviewer and focus, and violet for the candidate's voice only (The Two Voices Rule).
- **Do** make stage actions ink pills; keep End Red for ending alone.
- **Do** write every state in words beside its dot or colour.
- **Do** use 20px panes on cool paper with hairline borders and the Rest shadow.
- **Do** move on `cubic-bezier(0.22, 1, 0.36, 1)`, 260 to 420ms, and stop keyframe motion under reduced motion.
- **Do** use tabular numerals for time and codes.
- **Do** honour reduced transparency, more contrast and forced colours with explicit fallbacks.

### Don't:
- **Don't** show the interviewer as a face, avatar or video tile, or line the controls up as a bar of round icons.
- **Don't** use violet on buttons, links, focus rings or status.
- **Don't** use a solid red anywhere but ending the interview.
- **Don't** put notices over the transcript's newest lines.
- **Don't** set section labels or captions in tracked capitals; the caps belong to the mark.
- **Don't** load web fonts; the system stack is the type.
- **Don't** add stock photography or illustration; the only pictures are the live camera feeds, and none may be invented.
