# ADR-0047: One interview's analytics on the candidate page and the interview page

- **Status:** Accepted
- **Date:** 2026-11-21
- **Sub-project:** C8-7 (API, recruiter web app, interview agent)

## Context

The product owner asked: "after completing the interviews of the candidates i need to see the complete analytics in the recruitment dashboard for that particular candidates".

What existed for one interview, checked page by page with the owner's real interview of 2026-11-21:

- The interview page, as one long stack of cards: the transcript, the live monitoring list, the evaluation and the history.
- The interview, proctoring and coding reports: PRD §68 and §69's sections, as tables (the interview report is a 13,000-pixel document).
- Candidate 360's tabs, including the AI interview's scores.

All of it was correct, but nothing showed the interview at a glance: no chart, and none of PRD §59's speech measures.

The owner's interview showed one more thing: the stored answers were too short. Its transcript gave a pace of 450 words a minute, which no one speaks.
- The agent took an answer's start from the latest moment the candidate started speaking.
- Voice activity reports each pause mid-answer as speech stopping and starting again.
- So each answer was stored as only its last stretch of speech: short answers and long waits.

## Decision

### The data: `GET /interviews/{id}/analytics`

- **Who can see it:**
  - It needs `reports.interview.view`, and uses the same scoped access as the interview report. Each view is audited as `report.viewed` with kind `analytics`.
  - Its integrity part is null for a viewer without `reports.proctoring.view`.
- **Where it comes from:** `hirevion_core.reports.analytics` computes everything from `load_interview_data`, the reports' own loader. Nothing new is stored.
- **What it returns:**
  - **Overview:** the planned and actual length, the overall and communication scores (a reviewer's change included), and the questions put to the candidate.
  - **Per question:** its kind, skill, level, status, the live analysis's verdict and the evaluation's score. Also when it was asked, the wait before the answer (from the end of the question to the start of the answer), the speaking time and the words.
  - **Skills:** the engine's own coverage (as on the transcript page) with each skill's score, matched without case. A skill only the evaluation scored is added, counted from its questions.
  - **Speech (PRD §59):**
    - speaking time on each side and the candidate's share;
    - words, and pace in words a minute;
    - the median wait before answering, and waits over 10 seconds;
    - filler words, meaning hesitation sounds only ("um", "uh", "er", "hmm"…), and their rate per 100 words. "You know" and "I mean" are as often plain words. A word starts with a letter or a digit, so a dash is none.
    - A pace over 300 words a minute is not shown (`pace_unreliable`): the stored times are too short.
  - **Integrity:**
    - events by severity, leaving out those a reviewer dismissed and the process list (a record, not a detection);
    - each event's time from the start, and its review;
    - the process list at the start (ADR-0046) when there is one.

### The dashboard: `InterviewAnalyticsPanel`

The panel sits in a new Analytics tab on the candidate page (the latest interview first, with a picker when there are several), and in an Analytics section on the interview page once the interview is completed. It has six parts:
- **Headline numbers:** stat tiles for the overall score, communication, length against the plan, questions answered, the typical wait before answering, and critical proctoring events.
- **Score per skill:** a meter list with each skill's score out of 10, whether it is required, and whether it was covered or dropped.
- **Score per question:** a column chart of the answered questions in order, with each one's number and level under its column. Hovering or focusing a column names its question in a line under the chart, which the chart's scroll area can't clip.
- **Time per answer:** one bar per question, stacking the wait before answering and the speaking time, with a legend.
- **Speech:** who spoke (a thin split bar) and the §59 measures. It states that these are signals for a reviewer and never proof (§57, §59).
- **Integrity:** the counts by severity, the events as dots on the interview's timeline (along its planned length when it has no end yet), a count per event type, and the process list at the start grouped by program ("svchost ×86").

A table view of every question's numbers sits under the charts.

### How the charts are drawn

The charts follow the dataviz skill:
- plain HTML and CSS, no chart library;
- bars at most 24 pixels thick with a 4-pixel rounded data end, recessive hairline grids, a legend for the two-series bar, and tooltips on hover and focus.

The two series colours are new design tokens, `--chart-1` (indigo) and `--chart-2` (orange). They passed the palette validator on both surfaces: in light, `#4f46e5` and `#eb6834`; in dark, `#6366f1` and `#d95926` (indigo-400 is too light for a mark there). Severity dots use the status colours, always with a badge or a label.

### Blind review

- The AI's numbers (the overall and communication scores, skill and question scores) stay hidden until the reviewer has scored every question or chosen to skip (`useEvaluationGate`, ADR-0031), like every other panel that shows them.
- Nothing about them shows until the reviewer's own scores have loaded, so the "hidden" banner never flashes for someone who has already scored.
- Timing, speech and integrity always show.

### The agent: an answer is from its first speech to its last

- `hirevion_interview_agent.turns.SpeechWindow` keeps an answer's start at its first speech and its end at its last stop.
- Speech that resumes clears the end, and a stop with no start belongs to no answer.
- The agent takes the window when the answer arrives, so speech from then on belongs to the next answer.
- It clears the window when the interviewer starts speaking and when a turn has no words, so a cough the recogniser dropped never starts the next answer.

## Consequences

- **One page per interview:** a recruiter sees the whole interview, from the candidate page or the interview page.
- **Older interviews:**
  - Interviews recorded before the agent fix show "Not measured" for the pace.
  - A note says their speaking times are too short and their waits too long. Their transcripts keep the times they were stored with.
- **Filler words** depend on the speech recognition: Deepgram's `filler_words` is on, but it can leave some out, as the dashboard says.
- **Verified:**
  - Python tests for the speech and timing measures, the pace guard and the route (on a simulated, evaluated interview with telemetry), plus the authorization matrix.
  - Agent tests for the speech window.
  - Web tests for the chart arithmetic, the panel (scores hidden and revealed, the timeline, the grouped processes, the pace note, no integrity) and the candidate tabs.
  - A Playwright review of the real page with the owner's interview at three widths in light and dark: no sideways scrolling, no errors.
