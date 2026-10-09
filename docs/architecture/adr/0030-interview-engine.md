# ADR-0030: The interview engine: a deterministic policy over a checkpointed state, one conductor for every turn

- **Status:** Accepted
- **Date:** 2026-10-09
- **Sub-project:** SP-09 (a, b and c)

## Context

- **PRD §34** forbids "one giant prompt" and names the state's twelve fields and nine components. **§35** lists the stages; **§36** to **§40** ask for resume-based questions with their source, JD skill coverage, adaptive follow-ups, a difficulty ladder and a time controller. **§41** to **§43** ask for a timed, two-sided transcript. **§91** lists the live events.
- **Master plan §6.8** decides the division of labour: Python decides, models analyse and phrase. It also sets the latency path (p95 ≤ 2.5 s to first audio), a checkpoint every turn, recovery after an agent crash, and pause and recap after a disconnect.
- **`docs/api/contracts/interview-session.md`** (lane B, reviewed by lane C) fixes the desktop's calls and the `hv.state` and `hv.control` data topics.
- **Answers arrive two ways:** spoken, through the LiveKit agent, or typed, through the API with the text-answers accommodation (§90). Either process can die mid-interview.

## Decision

- **`hirevion_core.engine` is a pure, deterministic policy:**
  - The state (`InterviewState`) holds §34's twelve fields, plus the stage history, the question pool, the clock and the open question. It round-trips through JSON.
  - The nine components act in §34's order. Only `ContextBuilder` reads the database. Only `AnswerAnalyzer` (fast tier, 4 s budget) and `FollowUpGenerator` (a targeted follow-up with no recruiter rule) call a model.
  - Each model call falls back to a deterministic heuristic or template on any failure. The mock profile answers analysis with the same heuristic (`ai.mock.respond_with`), so CI interviews behave like real ones.
  - The `Orchestrator` takes the analysis as input and returns a `Turn`: what to say, the question asked, the answer to record, the questions closed, the events, and whether the interview ended.
- **Stages:** §35's ten are recorded with their times.
  - The ladder runs per skill (§37's skill order) along the template's difficulty mix. A strong answer moves one rung up and a weak one one rung down.
  - Each main question gets at most one follow-up: the recruiter's rule first, then a targeted question or a clarification.
  - Two weak answers in a row move on to the next skill.
  - Coding comes after the ladder. Final questions are answered only from the organisation's FAQ; anything else is passed on to the recruiter.
  - `evaluation` is the hand-off to SP-10.
- **Coverage and time:**
  - A required skill is one the JD marks required, or every template skill when the job has none. Required JD skills the template leaves out get a question.
  - When time runs short, follow-ups stop first. Then optional skills' extra questions go, then covered required skills' extras. An uncovered required skill always keeps one question.
- **Sources (§36):** every asked question is stored with its `source` (pinned, library, resume, generated, follow-up, FAQ, system) and its `source_ref`: the library version, or the resume's field, index, quote, page and section.
- **Guardrails:**
  - Deterministic intents are recognised before any model sees the text: repeat, need a moment, don't know, silence, no more questions, and manipulation (instruction overrides, asking for scores or answers). Manipulation is answered neutrally, flagged, and never counts as an answer.
  - Answers that read as pasted from an AI tool, or that repeat an earlier answer, are flagged for review. These are never verdicts.
  - An output guard (a short spoken question; no markdown; no scores, ratings or "correct answer") screens model text before it is spoken.
- **One `Conductor` runs every turn, whoever takes it** (the API in text mode, the agent in voice mode):
  1. a Valkey turn lock;
  2. load the checkpoint;
  3. the model calls, with no transaction open;
  4. step the orchestrator;
  5. one transaction writes the checkpoint under an optimistic `state_seq`, together with the question, the answer, the questions it closed, both transcript segments, the events and any completion;
  6. after commit, the §91 events go to `hv:rt:interview:{id}` and a hot copy to Valkey.

  So every committed turn survives a crash, and an uncommitted answer is simply asked for again.
- **Media (behind `MediaControl`, with a fake for CI):**
  - The room is `iv-{id}`.
  - The candidate's token can join only that room, subscribe, publish the microphone, camera and screen share, and send data.
  - The agent `hirevion-interviewer` is dispatched explicitly with the interview in its metadata.
  - LiveKit's signed webhooks drive the rest. The candidate leaving interrupts the interview (the clock pauses); the agent leaving an interview that's still running dispatches another.
- **Continuity:**
  - The agent holds `hv:iv:{id}:agent` (8 s TTL, refreshed every 3 s). A replacement waits for it, then resumes from the checkpoint with an apology and the open question, within about 10 s.
  - `start` within the resume policy's grace and interruption limit resumes with a recap. The scheduler abandons interviews interrupted for longer than the grace.
- **The agent never lets a model reply:**
  - `on_user_turn_completed` hands the final transcript to the conductor and raises `StopResponse`. It plays a short acknowledgement while the analysis runs, then speaks the turn.
  - The pronunciation lexicon is applied in `tts_node`, so captions keep the written form. Deepgram is primed with keyterms from the skills, the job and the resume.
  - Chat text input is off.
- **Transcripts and events:**
  - Segments are partitioned by month, like the other high-volume tables.
  - A consumer of `interview.completed` writes the JSON, VTT and TXT artifacts to `{org}/interviews/{id}/transcript/` with their SHA-256.
  - Recruiters read `GET /interviews/{id}/transcript` and follow `/ws/interviews/{id}`. The websocket needs an allowed Origin, a live session, `interviews.view` and the interview's scope; it replays from `?after=`. Events carry no scores.
- **Before the interview:** the itemised notice (§83, `NOTICE_VERSION`), system checks and consents are insert-only records. Accommodations approved by a recruiter change the policy before the start:
  - `text_answers` switches to text mode and makes the microphone check optional;
  - `third_eye_waiver` waives the phone camera requirement;
  - `extended_time` makes the interview 1.5 times as long;
  - `breaks` doubles the resume grace.
- **Contract additions** (recorded in `interview-session.md`):
  - the state gains `question`, `voice`, `stage` and `message`;
  - the `error` voice state;
  - `409 question-not-current`, `422 unknown-purpose` and `413 workspace-too-large`;
  - fake media outside production.

## Consequences

- **Testing:** every turn is reproducible from its checkpoint, and the whole engine is unit-tested without a database or network. The six simulator personas finish full interviews in CI on the mock AI.
- **No real voice in CI:** the live voice path (LiveKit, Deepgram, the agent's p95) can only be measured on the Windows machine. The voice benchmark and B5's chaos drills cover it.
- **The heuristic only steers the conversation:** it is no evaluation. SP-10's evaluator scores the answers with evidence and must not reuse the live analysis as a score.
- **Prompts are versioned files** (`interview-analyze-v1`, `interview-follow-up-v1`); changing one goes through SP-10's eval harness.
- **A required third eye can't start yet:** until SP-13 adds pairing, `start` answers `409 third-eye-required` unless the waiver is approved.
- **Hand-offs:**
  - SP-14 calls `Conductor.note_proctor_event` to fill §34's proctor summary and the CRITICAL-event reminder.
  - SP-12, SP-13, SP-14 and SP-16 add their §91 events to the same stream.
  - SP-16 replaces the coding stub's grading.
