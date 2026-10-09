# SP-09 AI Interview Engine Implementation Plan

**Goal:** PRD §29–§43, §83, §90 and §91 as the master plan's §6.8 describes them, implementing `docs/api/contracts/interview-session.md`. Lane C's parts C1 (SP-09a), C2 (SP-09b) and C3 (SP-09c), built together because each needs the others to run an interview end to end:
- **SP-09a:**
  - rooms, least-privilege participant tokens and explicit agent dispatch;
  - the voice pipeline (Deepgram STT and TTS through the LiveKit plugins; mock in CI);
  - §35's ten states;
  - `tools/interview-simulator` and its six personas.
- **SP-09b:**
  - §34's nine components over the twelve state fields;
  - per-question time limits and follow-up rules;
  - coverage and provenance;
  - the difficulty ladder and time control;
  - final questions from the FAQ;
  - text-answer mode;
  - guardrails.
- **SP-09c:**
  - transcript segments and artifacts (JSON, VTT, TXT);
  - §91's events;
  - per-turn checkpoints, the resume policy and crash recovery.

**Architecture:**
- **`hirevion_core.engine`** holds the policy. It is pure Python: no database, no network.
  - `state` holds the twelve §34 fields plus the stage, plan and clock, and round-trips through JSON.
  - The components follow §34: `ContextBuilder` (the only one that reads the database), `SkillMatrixBuilder`, `QuestionPlanner`, `AnswerAnalyzer` (the only LLM caller besides follow-up phrasing), `DifficultyController`, `FollowUpGenerator`, `CodingController` (a stub until SP-16), `TimeController`, `CompletionEvaluator`.
  - Supporting modules: guardrails, the FAQ matcher, the deterministic phrasing and the TTS lexicon.
  - The `Orchestrator` steps a state with an analysed answer, a control or a clock tick, and returns what to say.
- **`hirevion_core.interview_session`** handles the interview around the engine:
  - the briefing, system checks, consents and accommodations;
  - the `Conductor`, which runs every turn under a Valkey lock. It loads the checkpoint, analyses with no transaction open, steps, then saves with an optimistic `state_seq` and writes questions, answers and transcript segments in the same transaction;
  - transcripts and their artifacts;
  - realtime events, on the Valkey stream `hv:rt:interview:{id}`;
  - `media`: LiveKit rooms, tokens and dispatch behind a `MediaControl` protocol, with a fake for tests.
- **The API:**
  - the desktop routes from the contract, guarded by the interview-session token;
  - `POST /livekit/webhook`, verified by LiveKit's signed JWT;
  - recruiter routes: transcript, accommodations, and the organisation's interview briefing;
  - `/ws/interviews/{id}` for the live events.
- **`interview-agent`:**
  - a LiveKit worker with explicit dispatch;
  - each final transcript goes to the `Conductor`; the agent speaks what comes back and stops the LLM reply (`StopResponse`);
  - `hv.state` and `hv.control` data topics;
  - the lexicon applied in `tts_node`, keyterms primed in STT;
  - an agent lock in Valkey, and a recap on resume.
- **`tools/interview-simulator`:** a desktop client with DPoP and six personas. It drives the API in text mode, through ASGI in CI and over HTTP locally.

## Decisions (defaults; the product owner asked to build without stopping)

- **Stages (§35):** `start`, `introduction`, `easy`, `medium`, `hard`, `follow_up`, `coding`, `final_questions`, `completion`, `evaluation`. Each change is recorded with its time. A main question's stage is its difficulty, so the ladder runs per skill (§37's skill order) along the template's difficulty mix. `evaluation` is the hand-off to SP-10, which takes the `interview.completed` event.
- **Voice states (§33):** `hv.state.voice` is one of `listening`, `thinking`, `speaking`, `waiting` (§33's Idle), `paused` and `ended`, plus `error` for §33's Error. That last one is a contract addition.
- **Skills:**
  - The template's skills and weights apply. With `use_jd`, any required JD skill the template leaves out gets one question, taken from the skill with the most.
  - A skill is *required* when the job marks it required, or, when the job has no skills, when it is in the template.
  - A skill counts as *covered* once one of its main questions has been answered, whatever the quality.
- **Planning:**
  - Each skill gets its share of `question_count` and a ladder from the difficulty mix (`allocate`).
  - Questions come from three places, in order:
    1. the template's pinned questions;
    2. approved library questions (current versions), in an order seeded by the interview id, so candidates vary and re-runs repeat;
    3. a generated question for any gap.
  - With `use_resume` and a resume or project type allowed, a skill with resume evidence opens with a resume question (§36). It quotes the evidence, and `source_ref` keeps the field, index, quote, page and section.
  - Generated and resume questions are phrased by templates, so the plan never waits on a model.
- **Analysis (§38):**
  - The answer is analysed for correctness, completeness and depth (0–1), missing concepts, contradictions, a quality of `strong`, `partial`, `weak` or `no_answer`, and two flags: off-topic and manipulation.
  - The LLM call is `interview.analyze` (fast tier, prompt `interview-analyze-v1`) with a 4 s budget. Any failure or timeout falls back to a deterministic heuristic: expected-concept coverage, length and hedging.
  - The mock profile answers with the same heuristic (a mock responder), so CI runs are meaningful and repeatable.
- **Follow-ups:** only with `adaptive_follow_ups`, at most one per main question, and only when time allows.
  - A strong answer gets the question's `strong` rule, if it has one; otherwise it moves the skill up a rung.
  - A partial answer gets the `partial` rule, or a targeted question on the missing concepts. That question comes from `interview.follow_up` (fast tier) and must pass the output guard, or a template is used.
  - A weak answer gets the `weak` rule or a template clarification.
  - Two weak answers in a row move on to the next skill. The skill's remaining questions are dropped, but it is still covered.
- **Difficulty (§39):** the next question's rung is its target on the skill's ladder, one higher after a strong answer and one lower after a weak one, between easy and hard. If no question exists at that rung, the nearest rung is used, then a generated question.
- **Time (§40):**
  - **Deadline:** start plus the duration (×1.5 with approved extended time), plus paused time when the resume policy pauses the timer.
  - **Question budgets:** the question's time limit, or by type: 180 s, scenario and system design 300 s, coding the template's coding minutes.
  - **Reserve:** 150 s is held back for final questions and the close.
  - **Shrinking:** when the plan no longer fits, follow-ups stop first. Then optional skills' extra questions are dropped, lowest weight first. Each uncovered required skill keeps one question.
  - **Overruns:** a question past its time limit is closed as `timed_out`. A late text answer is still kept, marked `late`.
- **Coding:** with coding on, one approved coding question in the template's languages comes after the ladder, with workspace `code`. No such question means the stage is skipped and an event records it. SP-16 adds running and grading.
- **Final questions:**
  - The FAQ match is a deterministic token overlap. The engine answers only from the organisation's FAQ (`organization_settings.interview_briefing`).
  - With no match, the engine says it will pass the question on, and records it for the recruiter.
  - At most three questions, or fewer if the candidate says that's all.
- **Guardrails:**
  - Deterministic intents are recognised before any model: repeat, need a moment, don't know, silence, and manipulation (instruction overrides, asking for scores or answers).
  - A manipulation attempt is answered neutrally, flagged in the answer and the interview's events, and does not count as an answer. A second attempt on the same question moves on.
  - **Output guard:** model text must be under 400 characters, a question, free of markdown, and mention no score, rating or "correct answer", or a template is used.
- **Answer modes:**
  - `voice`: the agent conducts.
  - `text`: with the approved `text_answers` accommodation, the API conducts in `POST /answer`.
  - Both go through the same `Conductor`. A text answer in voice mode is also accepted, and the agent speaks whatever question it didn't start itself, by following the events stream.
- **Checkpoints and recovery:**
  - Every turn commits the state (`interview_sessions.state`, `state_seq`) together with its rows; Valkey keeps the hot copy and the voice state.
  - The agent holds `hv:iv:{id}:agent` (an 8 s TTL, refreshed every 3 s).
  - **Agent leaves:** when LiveKit's webhook says the agent left an interview in progress, the API dispatches another. That agent waits for the lock, loads the checkpoint and repeats the open question with an apology, so no turn is lost: an answer that wasn't committed is asked for again.
- **Resume policy:**
  - When the candidate leaves the room, the interview moves to `interrupted` (`interrupted_at`) and the clock pauses.
  - `start` again within `grace_seconds` and under `max_interruptions` resumes it with a recap. Otherwise the answer is `409 resume-limit-reached`.
  - The scheduler abandons an interview that stays interrupted past its grace period.
- **Rooms and tokens:**
  - The room is `iv-{interview_id}`.
  - The candidate's identity is `candidate-{candidate_id}`. Their token may join that room, subscribe, publish the microphone, camera and screen share, and send data; nothing else. It expires at the earlier of the session token's end and the deadline plus 15 minutes.
  - The agent `hirevion-interviewer` is dispatched explicitly with `{interview_id, organization_id}` as metadata.
- **Transcripts (§41, §43):**
  - Each segment stores the speaker (`ai`, `candidate`), text, start and end in milliseconds from the start, the question id and the confidence. Both sides are stored, in the turn's transaction.
  - Segments live in `transcript_segments`, partitioned by month like the other high-volume tables.
  - On completion, a consumer of `interview.completed` writes the JSON, VTT and TXT artifacts to `{org}/interviews/{id}/transcript/`, and records them with their SHA-256 in `transcripts`.
- **Events (§91):** SP-09 publishes `AI_SPEAKING`, `CANDIDATE_SPEAKING`, `QUESTION_STARTED`, `ANSWER_RECEIVED` and `INTERVIEW_COMPLETED`; SP-12, SP-13, SP-14 and SP-16 add the rest to the same stream.
  - Each event is `{type, interview_id, at, data}`, kept on a capped Valkey stream.
  - `/ws/interviews/{id}` replays from `?after=` and then follows. It needs the recruiter's session cookie, an allowed Origin, and `candidates.view` or being a reviewer.
  - Events carry no scores.
- **Consent (§83):**
  - The notice lists the purposes that apply to the policy; each is required when the policy needs it. `NOTICE_VERSION` is `2026-10-09`.
  - Consents and system checks are insert-only records.
- **Accommodations:**
  - A candidate requests them. A recruiter with `interviews.manage` approves some or all of them, or declines; this is audited.
  - Approved kinds go into `policy.accommodations`:
    - `text_answers` sets the answer mode to text and takes the microphone off the mandatory checks;
    - `third_eye_waiver` takes off the third eye;
    - `extended_time` stretches the deadline;
    - `breaks` doubles the resume grace;
    - `relaxed_gaze` is for SP-14;
    - `assistive_technology` is for SP-11's process rules.
- **Contract additions** (recorded in `interview-session.md`):
  - the state gains `question`, `voice` and `stage`;
  - `409 question-not-current` and `422 unknown-purpose`;
  - the `error` voice state;
  - `413 workspace-too-large` (over 256 KB).

## Tasks

1. **Schema (migration 0015):**
   - tables: `system_check_results`, `consents`, `accommodations`, `interview_sessions`, `interview_questions`, `interview_answers`, `workspace_snapshots`, `transcripts`, `transcript_segments` (partitioned);
   - `organization_settings.interview_briefing` and `interviews.interrupted_at`;
   - the scheduler function abandons expired interruptions.

   Isolation and models-match tests.
2. **Engine:** state and the nine components, guardrails, FAQ, phrasing, lexicon and the orchestrator. Unit tests for each rule above, including the ladder, follow-ups, shrinking, coverage and the guard.
3. **The session around the engine:**
   - the briefing, checks, consents and accommodations;
   - the conductor with its lock, checkpoints and rows;
   - media with a fake;
   - transcripts and artifacts;
   - realtime events;
   - interrupt, resume and abandon.

   Tests against the database.
4. **API:**
   - the contract's routes, the webhook, the recruiter routes and the websocket;
   - the matrix's unguarded list (`candidate`, `webhook`);
   - OpenAPI and codegen.

   Contract tests with a DPoP desktop.
5. **Agent:** the conductor-driven agent, the lexicon, keyterms, `hv.state`/`hv.control`, the agent lock and the recap. Unit tests with a fake session.
6. **Simulator:** the client and the personas (strong, partial, weak, silent, adversarial, cheating), plus `hv interview-sim`. Each persona must finish a full interview with required skills covered (CI, mock). A killed conductor process resumes from the checkpoint with no lost turn.
7. **Web:**
   - the interview page's transcript, coverage and accommodation decisions;
   - the organisation's interview briefing (instructions and FAQ).

   Component tests and a Playwright spec.
8. **Docs:** ADR-0030, runbook, threat model, Appendix A (§29–§43, §83, §90, §91), PENDING_TASKS.md C1–C3.
