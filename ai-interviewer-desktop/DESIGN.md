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
  brand-from: "#2f8bff"
  brand-to: "#8b5cf6"
  stage-ground: "#f3f5fb"
  stage-glow-blue: "rgb(110 150 255 / 0.22)"
  stage-glow-violet: "rgb(170 140 255 / 0.16)"
  card-glass: "rgb(255 255 255 / 0.86)"
  card-edge: "rgb(120 130 170 / 0.16)"
  card-rule: "rgb(120 130 170 / 0.12)"
  pill-grey: "#eef1f7"
  heading-ink: "#14183a"
  ai-ink: "#1d5bd8"
  ai-tint: "#edf3ff"
  ai-edge: "#dce7ff"
  you-ink: "#6a3de0"
  you-tint: "#f4eeff"
  you-edge: "#e8ddff"
  wave-violet: "rgb(150 140 255 / 0.1)"
  wave-blue: "rgb(120 165 255 / 0.1)"
  orb-highlight: "#9bf0ff"
  orb-interviewer: "#2c6bff"
  orb-interviewer-edge: "#8d4dff"
  orb-candidate: "#8b5cff"
  orb-candidate-edge: "#4c2fc0"
  success: "#1b7438"
  success-wash: "#e7f6ec"
  warning: "#8a5300"
  warning-wash: "#fff4dc"
  danger: "#b3261e"
  danger-wash: "#fdecea"
  end-red: "#c9241c"
  end-red-light: "#ef4040"
  camera-black: "#10121a"
  dark-ground: "#0e0e10"
  dark-ink: "#f5f5f7"
  dark-surface: "#1c1c1e"
  dark-surface-muted: "#2a2a2d"
  dark-hairline: "#38383b"
  dark-muted-ink: "#a6a6ad"
  dark-interviewer-blue: "#409cff"
  dark-blue-wash: "#0c2743"
  dark-brand-from: "#4d9bff"
  dark-brand-to: "#a07bff"
  dark-stage-ground: "#0c0e15"
  dark-card-glass: "rgb(23 25 34 / 0.88)"
  dark-pill-grey: "#232633"
  dark-heading-ink: "#f2f3f8"
  dark-ai-ink: "#8fb4ff"
  dark-you-ink: "#bba6ff"
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
  card-title:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 600
    letterSpacing: "-0.01em"
  bar-title:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.1rem"
    fontWeight: 400
  body:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  transcript:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 400
    lineHeight: 1.45
  speaker:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 600
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
    fontSize: "1.35rem"
    fontWeight: 600
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  wordmark:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 700
    letterSpacing: "0.01em"
  watermark:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.7rem"
    fontWeight: 600
    letterSpacing: "0.03em"
rounded:
  chip: "8px"
  field: "12px"
  inset: "14px"
  tile: "16px"
  pane: "20px"
  card: "22px"
  pill: "9999px"
spacing:
  hair: "6px"
  xs: "0.5rem"
  sm: "0.9rem"
  md: "1rem"
  gutter: "1.1rem"
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
    rounded: "{rounded.pill}"
    height: "2.9rem"
    padding: "0 1.4rem"
  button-jump-latest:
    backgroundColor: "{colors.heading-ink}"
    textColor: "{colors.cool-paper}"
    rounded: "{rounded.pill}"
    height: "2rem"
    padding: "0 0.85rem"
  pane:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.pane}"
  stage-card:
    backgroundColor: "{colors.card-glass}"
    rounded: "{rounded.card}"
  stage-card-header:
    textColor: "{colors.heading-ink}"
    typography: "{typography.card-title}"
    height: "4rem"
    padding: "0.85rem 1.25rem"
  top-bar:
    backgroundColor: "{colors.card-glass}"
    textColor: "{colors.heading-ink}"
    rounded: "{rounded.card}"
    height: "4.75rem"
    padding: "0 1.25rem"
  brand-tile:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.inset}"
    size: "2.9rem"
  card-pill:
    backgroundColor: "{colors.pill-grey}"
    textColor: "{colors.muted-ink}"
    rounded: "{rounded.pill}"
    height: "2rem"
    padding: "0 0.9rem"
  clock-pill:
    backgroundColor: "{colors.pill-grey}"
    textColor: "{colors.heading-ink}"
    typography: "{typography.clock}"
    rounded: "{rounded.pill}"
    height: "2.9rem"
    padding: "0 1.1rem"
  orb-state-pill:
    backgroundColor: "{colors.ai-tint}"
    textColor: "{colors.ai-ink}"
    rounded: "{rounded.pill}"
    height: "2.2rem"
    padding: "0 1rem"
  orb-state-pill-candidate:
    backgroundColor: "{colors.you-tint}"
    textColor: "{colors.you-ink}"
  orb-state-pill-quiet:
    backgroundColor: "{colors.pill-grey}"
    textColor: "{colors.muted-ink}"
  turn-interviewer:
    backgroundColor: "{colors.ai-tint}"
    textColor: "{colors.heading-ink}"
    typography: "{typography.transcript}"
    rounded: "{rounded.tile}"
    padding: "1rem 1.15rem"
  turn-candidate:
    backgroundColor: "{colors.you-tint}"
    textColor: "{colors.heading-ink}"
    typography: "{typography.transcript}"
    rounded: "{rounded.tile}"
    padding: "1rem 1.15rem"
  turn-avatar:
    rounded: "{rounded.pill}"
    size: "2.75rem"
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
  camera-frame:
    backgroundColor: "{colors.camera-black}"
    rounded: "{rounded.inset}"
  camera-watermark:
    backgroundColor: "{colors.camera-black}"
    textColor: "{colors.surface}"
    typography: "{typography.watermark}"
    rounded: "{rounded.chip}"
    padding: "0.35rem 0.6rem"
---

# Design System: Hirevion Candidate App

## Overview

**Creative North Star: "The Quiet Stage"**

The candidate app is a calm room in which the conversation is the interface. Outside the interview, a cool paper ground carries white panes on hairline borders and almost everything is ink and grey. The interview itself follows the product owner's reference image (2026-11-24): a soft blue-violet ground lit by faint glows, on which everything floats as a translucent white card, the top bar included. Colour is spent on meaning: blue for the AI Interviewer, violet for the candidate, one brand gradient for the mark, red only for ending, and green, amber and red for live state. The interviewer is not a face but a vivid sphere of light carrying the waveform mark, moving with the real sound, and both voices are written down beneath it as tinted turn cards.

The system stays Apple-inspired in its restraint (the owner's binding direction): the system font, soft radii, pill buttons that press in at once, soft shadows, translucent glass with a solid fallback, and motion on a single long-tail ease that settles rather than bounces. It is dense enough for a working interview on a 1280 by 720 laptop and never scrolls the window; a screen's own content scrolls when it must.

It refuses the video-call default: no grid of faces, no bar of round icon buttons. Every state that needs the candidate's attention is said in words as well as colour.

**Key Characteristics:**
- On the stage: a blue-violet ground, 22px translucent cards, a floating top bar, heading ink.
- Elsewhere: cool paper ground, white 20px panes, hairline borders, ink text.
- Blue is the interviewer, violet the candidate, the gradient the mark; nothing is colour for decoration.
- A vivid orb with the waveform mark as the interviewer's only presence, moving with live sound.
- The system font, tabular figures for time, tracked capitals only in the mark and the watermark.
- Light and dark themes from one token set; every system preference is honoured.

## Colors

Cool greys and heading ink, two speaker hues, one blue-to-violet brand gradient and one destructive red, each kept to its job.

### Primary
- **Interviewer Blue** (`interviewer-blue`): the app's accent outside the interview (primary pill buttons, quiet links) and every focus ring, on every screen. Dark theme: `dark-interviewer-blue`.
- **Blue Wash / Blue Wash Ink** (`blue-wash`, `blue-wash-ink`): accent status pills and soft blue fills on the screens around the interview.
- **AI Blue** (`ai-ink`, `ai-tint`, `ai-edge`): the AI Interviewer's voice on the stage: its turn cards (tint with an edge), its name above each turn, and the orb's state pill while it speaks. Dark theme: `dark-ai-ink` with translucent tints.

### Secondary
- **Candidate Violet** (`you-ink`, `you-tint`, `you-edge`): the candidate's own voice and nothing else: the candidate's turn cards, the "Candidate" name and avatar, and the orb's state pill while the candidate speaks. Dark theme: `dark-you-ink` with translucent tints.

### Tertiary
- **Brand Gradient** (`brand-from` into `brand-to`): the mark's colour: the emblem on its white tile in the top bar, the bars of the voice strip, the interviewer's avatar (into a deeper blue), and a muted hint in the drawn coding placeholder. Dark theme: `dark-brand-from`, `dark-brand-to`.
- **Orb Light** (`orb-highlight`, `orb-interviewer`, `orb-interviewer-edge`, `orb-candidate`, `orb-candidate-edge`): the stops of the orb's radial gradients only. The interviewer's orb runs cyan highlight to blue to violet; the candidate's runs pale lilac to violet to deep indigo. Never used as flat fills elsewhere.
- **End Red** (`end-red`, lit from `end-red-light`): the one solid red, on End Interview (a top-down gradient) and its confirmation.

### Neutral
- **Stage Ground** (`stage-ground`, with `stage-glow-blue` and `stage-glow-violet`): the interview's ground, washed by three soft radial glows (top centre, bottom right, bottom left).
- **Card Glass** (`card-glass`, `card-edge`, `card-rule`): stage cards and the top bar, their 1px edge and the rule under a card header. Turns solid `surface` under reduced transparency.
- **Pill Grey** (`pill-grey`): the clock pill, a card's state pill ("Waiting for question…"), quiet orb states, the placeholder drawing's screen.
- **Heading Ink** (`heading-ink`): titles, the bar title, transcript words, the question text and the "jump to latest" pill on the stage.
- **Cool Paper** (`cool-paper`): the window ground outside the interview.
- **Surface White** (`surface`): panes, panels, fields, the brand tile, the typed-answer pane.
- **Muted Surface / Sunken Surface** (`surface-muted`, `surface-sunken`): inset blocks in the preparation steps, neutral pills.
- **Hairline** (`hairline`): pane and panel borders off the stage. **Field Stroke** (`field-stroke`) edges inputs.
- **Ink / Muted Ink** (`ink`, `muted-ink`): text and secondary text. Ink also fills the stage's action buttons.
- **Waves** (`wave-violet`, `wave-blue`): two soft wave shapes along the bottom of the coding and interviewer cards.
- **Camera Black** (`camera-black`): behind camera feeds and their empty states.
- **Status** (`success`, `warning`, `danger` with their washes): status dots, status pills, notices, the clock at low and critical time.

### Named Rules
**The Two Voices Rule.** AI Blue is the interviewer, Candidate Violet is the candidate. Each speaker's turn cards, name and orb state carry its colour; the violet tokens never mark a button, a link, a focus ring or a status.

**The Gradient Is the Mark Rule.** Blue into violet belongs to the emblem and the things that carry its waveform: the brand tile, the orb, the voice strip and the interviewer's avatar. It is not a speaker signal and never fills a button, a card or text.

**The Ink Action Rule.** Inside the interview stage, action buttons are ink on paper, never blue, so blue keeps meaning "the interviewer". Outside the stage, the primary button is Interviewer Blue.

**The One Red Rule.** End Interview is the only solid red on any screen. Danger text and washes say a problem; solid red says "this ends it".

**The Words Too Rule.** Any device or session that is starting or has a problem writes its state beside its icon and dot, in the state's colour. A working item may show its icon and green dot alone; its full state is in its tooltip and accessible name. Colour never carries a problem by itself.

## Typography

**Display Font:** Segoe UI Variable Text (with Segoe UI, system-ui, -apple-system, sans-serif)
**Body Font:** the same system stack
**Label/Mono Font:** the same stack; figures use tabular numerals

**Character:** One native Windows face at a 15px root, set quietly: headings tightened to -0.02em and balanced, body at 1.5 line height, weight doing the hierarchy rather than size. On the stage, type is set a step larger and in heading ink so it reads at a glance during an interview.

### Hierarchy
- **Display** (600, 2rem, 1.25): the page heading on the interviews list and the preparation screen.
- **Headline** (600, 1.75rem, 1.25): a screen title with its one line of lead (max 60ch).
- **Title** (600, 1.1 to 1.2rem): step headings and interview cards.
- **Card Title** (600, 1.15rem, -0.01em, heading ink): a stage card's name ("Coding Question", "Main Camera"), one truncated line beside its lucide icon. The placeholder's own heading is 1.3rem.
- **Bar Title** (400, 1.1rem; the candidate's name at 600): the top bar's "name, job, Interview" line, truncated; 0.95rem below 1024px.
- **Body** (400, 1rem, 1.5): prose and leads; the coding placeholder's line in muted ink.
- **Transcript** (400, 1.05rem, 1.45, heading ink, max 62ch): the words in a turn card, under the **Speaker** name (600, 0.95rem) in the speaker's colour.
- **Question** (1.05rem, 1.55, max 70ch): the coding or notes prompt.
- **Label** (600, 0.72 to 0.8rem, 0.02em): pane titles and live labels on the screens around the interview. Sentence case, muted ink. On the stage, state pills use 0.85 to 0.95rem at 400 to 500.
- **Clock** (600, 1.35rem, -0.01em, tabular): the countdown in its pill beside a clock icon.
- **Wordmark** (700, 1.35rem, 0.01em, uppercase): "AI INTERVIEW" beside the emblem tile; visually hidden below 1280px. **Watermark** (600, 0.7rem, 0.03em, uppercase): "CONFIDENTIAL • INTERVIEW SESSION" on the camera picture. These are the only capitals.

### Named Rules
**The Figures Hold Still Rule.** Time and codes use tabular numerals so a ticking clock never shifts its neighbours.

**The Mark Owns the Caps Rule.** Uppercase belongs to the wordmark and the confidential watermark. Card titles, section labels and captions are sentence or title case, never tracked capitals.

## Layout

The window is a fixed frame that never scrolls; each screen scrolls its own content. The interview stage is a floating top bar (4.75rem tall, inset 1.25rem from the window's edges) over a three-card grid (coding question, interviewer, cameras) at `1fr 1.04fr 0.9fr`, with 1.1rem gaps and 1.1rem 1.25rem 1.25rem padding. When a coding or notes question opens, the grid eases to `1.4fr 1fr 0.8fr` over 420ms, the coding card slides in 16px from the left, and the orb shrinks from `clamp(8rem, 22vh, 12.5rem)` to `clamp(6.5rem, 16vh, 9.5rem)`; nothing jumps.

The top bar runs left to right: the emblem tile and wordmark, a 1px rule, the bar title (which takes the free width), the microphone, screen and session status, the clock pill, End Interview.

The interviewer card stacks the orb inside its rings, the state pill beneath it, any notices (always between the orb and the transcript, never over the newest words), the transcript, the typed-answer pane when text mode is on, then the voice strip and the waves. The camera column is one card per camera, sharing the height; each picture crops to fill its frame rather than squashing.

Breakpoints step down without changing the idea: at 1279px the bar and grid tighten to 0.9rem and the wordmark is visually hidden; at 1023px the stage becomes two columns (`1.2fr 0.8fr`) that scroll, the idle coding card is hidden, and camera frames go 4:3. With a question open at that width the question takes the left at full height, a 3.5rem orb sits beside its state pill above the cameras on the right, and the transcript and answer run full width below, with the voice strip and waves hidden. At 767px everything is one column and the cameras sit side by side. The window's minimum is 800 by 600.

Spacing runs on a small rhythm: 0.5rem inside chips and between lines, 0.85 to 1.1rem between stacked parts and turns, 1.1rem stage gutters, 1.25rem card and pane padding, 2rem for empty states.

## Elevation & Depth

The stage is layered glass: translucent cards (blur 18px, saturate 140%) with a soft, blue-tinted shadow float over a glowing ground. Off the stage, the app stays mostly flat, with depth from tone and hairlines and two neutral shadows. Under reduced transparency every card and bar turns solid surface with no blur.

### Shadow Vocabulary
- **Card** (`box-shadow: 0 1px 2px rgb(30 40 90 / 0.04), 0 20px 44px -24px rgb(60 70 140 / 0.22)`): every stage card and the top bar. Dark theme: 0.4 and 0.6 black.
- **Tile** (`box-shadow: 0 1px 2px rgb(30 40 90 / 0.06), 0 6px 14px -8px rgb(60 70 140 / 0.3)`): the brand tile; the interviewer's avatar takes a similar blue-tinted drop.
- **Red Lift** (`box-shadow: 0 10px 22px -10px` End Red at 75%): End Interview only.
- **Orb Glow** (a 3px inner white rim, a soft inner light, a 7px lilac halo at 32%, and `0 20px 50px -12px rgb(90 80 255 / 0.5)`): the orb only, with three rings outside it carrying their own soft light.
- **Rest** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.04)`): secondary buttons and panes off the stage.
- **Lift** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.04), 0 12px 32px rgb(0 0 0 / 0.07)`): panels on the other screens and the "jump to latest" pill. Dark theme raises both to 0.4 and 0.45 alpha.

### Named Rules
**The Floating Card Rule.** On the stage, everything sits on a 22px glass card with the Card shadow, including the top bar; there are no ruled bars or edge-to-edge chrome.

**The Real Sound Rule.** The orb, its rings and the voice strip scale only with the measured audio level; nothing pulses on a timer when nobody speaks. The one timed motion is the light travelling round the first ring (2.6s) while thinking, connecting or reconnecting, and the orb desaturates while not connected.

## Shapes

Soft, consistent corners that tighten as elements get smaller: 22px for stage cards and the top bar; 20px for panes, panels and dialogs; 16px for turn cards, notices, the typed-answer pane and inset blocks; 14px for camera frames and the brand tile; 12px for fields; 8px for the camera watermark chip; full pills for every button, state pill, the clock, status pills and dots. The orb is a perfect circle inside three concentric rings. The emblem is five rounded bars on a 24-unit grid with a dot over the centre bar, drawn in the brand gradient on its tile, white inside the interviewer's avatar, and in ink on plain surfaces; the orb carries a five-bar waveform glyph in white. Two soft waves run along the bottom of the coding and interviewer cards. Icons are lucide, at 1.75 to 2 stroke.

## Components

### Buttons
Pills that press in at once.
- **Shape:** full pill (9999px), 2.5rem tall (3rem large), medium weight.
- **Primary:** Interviewer Blue with white text, hover to the deeper blue. On the interview stage the same button is ink with paper text, hover to 84% ink.
- **Secondary:** white surface, hairline border, Rest shadow. **Quiet:** blue text, blue-wash on hover.
- **End Interview:** a 2.9rem pill lit from `end-red-light` down to End Red, 600 weight at 1rem, a filled stop square, the Red Lift shadow; hover dims to 94% brightness. It always opens a confirmation where Continue is the focused, safe choice.
- **Jump to latest:** a 2rem heading-ink pill with paper text and a down arrow, floating at the transcript's bottom centre when the candidate has scrolled back.
- **Press / Focus:** scale to 0.97 on press (off under reduced motion); a 2px focus ring in Interviewer Blue with 2 to 3px offset.

### Chips and Status
- **Status pill:** 1.75rem pill, the state's wash with its text colour, a 6px dot, a few words (screens around the interview).
- **Bar status:** in the top bar, a lucide icon (microphone, screen, lock) with a small dot at its corner ringed in surface; a state other than working also writes its word, and the whole item takes the state's colour.
- **Card pill:** a 2rem Pill Grey pill at a card header's end, muted text: "Waiting for question…" or "In progress".
- **Clock pill:** 2.9rem, Pill Grey with a Card Edge border, clock icon and tabular time in heading ink; amber on its wash at low time, red on its wash at critical time.
- **Camera status:** a dot and "Live", "Starting" or "Off" in the state's colour at the camera card's header end.

### Cards / Containers
- **Corner Style:** 22px on the stage; 20px panes elsewhere.
- **Background:** Card Glass on the stage ground; white surface on cool paper elsewhere.
- **Shadow Strategy:** Card on the stage, Rest or Lift elsewhere (see Elevation).
- **Border:** 1px Card Edge on the stage; 1px hairline (70% on the other screens' panels).
- **Header:** at least 4rem, 0.85rem 1.25rem padding, a lucide icon, a Card Title and an optional card pill, with a Card Rule beneath (camera cards drop the rule).

### Inputs / Fields
- **Style:** white field, Field Stroke border, 12px radius, 2.75rem tall on sign-in (the kit field is 2.25rem).
- **Focus:** the blue focus ring.
- **Error / Disabled:** danger border; 50% opacity.

### Notices
Something the candidate should know, said once: a 16px-radius block in a status wash and its text colour, faded in. On the stage they sit centred under the orb's state pill, at most 34rem wide.

### Top Bar (signature)
A floating glass card, 4.75rem tall: the emblem in the brand gradient on a white 2.9rem tile, "AI INTERVIEW", a short rule, the candidate's name in bold with the job and "Interview", the bar status, the clock pill and End Interview.

### Coding Question Card
Until the AI asks a coding or design question, the card shows "Waiting for question…" in its pill and a drawn open laptop with a code mark and a few sparkles, in Pill Grey and muted strokes, above "Coding question will appear here" (1.3rem, heading ink) and a muted line. When a question arrives it slides in from the left and holds the question (Question type) and its console or notes pad.

### Voice Orb (signature)
The interviewer's presence. A vivid sphere (clamp 8rem to 12.5rem; smaller when coding opens) lit from the upper left in Orb Light, a white waveform glyph at its centre, inside three soft rings that reach 40% beyond it. Its core and rings scale with the live audio level. Interviewer speaking: blue into violet. Candidate speaking: the sphere turns violet. Listening: the first ring settles to 70%. Thinking, connecting, reconnecting: a white light travels round the first ring, and the orb desaturates while not connected. Beneath it, a state pill says the state in words: AI Blue while the interviewer speaks, Candidate Violet while the candidate speaks, amber while reconnecting, Pill Grey otherwise. In Windows High Contrast it becomes a system-coloured ring with its glyph in CanvasText, and the rings, strip and waves are removed.

### Live Transcript (signature)
One card per speaker's turn: a 16px card in the speaker's tint with its edge, a 2.75rem round avatar (the white emblem on a blue gradient for the AI Interviewer; a violet user glyph on a violet-tinted disc for the candidate), the speaker's name in its colour, and the words in heading ink. Both voices are always tinted. Words still being heard are muted ink until final. New turns rise 6px and fade in over 260ms; the list fades out under a 1.75rem mask at its top edge.

### Voice Strip
Twenty-five 3px bars in the brand gradient at 80% opacity along the bottom of the interviewer card, in a fixed symmetric profile, scaling with the same audio level as the orb.

### Camera Tile
A stage card per camera: a header with its lucide icon (video or phone), its name and its live status, then the picture inset 0.85rem in a 14px Camera Black frame. The main camera is mirrored. A dark 8px chip at the picture's lower right carries "CONFIDENTIAL • INTERVIEW SESSION" in white, drawn over the picture only; it shrinks in narrow tiles. With no picture, a muted icon and a sentence sit on a dark radial ground, breathing slowly while the camera starts.

## Do's and Don'ts

### Do:
- **Do** keep AI Blue for the interviewer, Candidate Violet for the candidate's voice only, and Interviewer Blue for focus (The Two Voices Rule).
- **Do** keep the blue-to-violet gradient to the mark and what carries its waveform.
- **Do** make stage actions ink pills; keep End Red for ending alone.
- **Do** write a state in words whenever it isn't working.
- **Do** put stage content on 22px glass cards with the Card shadow over the stage ground, and use 20px white panes on cool paper elsewhere.
- **Do** move on `cubic-bezier(0.22, 1, 0.36, 1)`, 260 to 420ms, and stop keyframe motion under reduced motion.
- **Do** use tabular numerals for time and codes.
- **Do** use lucide icons and the system font.
- **Do** honour reduced transparency, more contrast and forced colours with explicit fallbacks.

### Don't:
- **Don't** show the interviewer as a face, photo or video tile; its presence is the orb and its avatar is the emblem. Don't line the controls up as a bar of round icon buttons.
- **Don't** use the violet tokens on buttons, links, focus rings or status.
- **Don't** use a solid red anywhere but ending the interview.
- **Don't** put notices over the transcript's newest lines.
- **Don't** set card titles, section labels or captions in tracked capitals; the caps belong to the mark and the watermark.
- **Don't** load web fonts; the system stack is the type.
- **Don't** add stock photography or invented imagery; the only pictures are the live camera feeds, and the only drawing is the coding placeholder. The synthetic people in the debug gallery are test data, not brand assets.
