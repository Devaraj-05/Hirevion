# ADR-0005: Voice pipeline and measured latency

- **Status:** Accepted
- **Date:** 2026-09-29
- **Sub-project:** SP-00c (spike 1)

## Context

The AI interviewer must answer quickly enough to feel like a conversation. The master plan's target is the AI's first spoken word at p95 ≤ 2.5 s after the candidate stops speaking.

The measurement:

- **Pipeline:** self-hosted LiveKit, LiveKit Agents 1.8.3, Deepgram speech-to-text (nova-3) and text-to-speech (Aura-2), and Gemini through its OpenAI-compatible API (development profile, ADR-0003).
- **Where it ran:** the development PC in India, over home broadband that was also streaming video.
- **Method:** `tools/voice_bench` plays a synthetic candidate into the room. It measures from the last audio frame of each spoken answer to the agent's first audible frame. The agent logs its own stages:
  - end of turn — voice detection to turn committed;
  - LLM time to first token;
  - TTS time to first byte.
- **Sample sizes:** 5 turns per configuration unless noted; the final configuration ran 20 turns.

| Configuration | Total p50 | Total p95 | LLM first token | End of turn | Result |
|---|---|---|---|---|---|
| gemini-2.5-flash | — | — | — | — | 404: "no longer available to new users" |
| gemini-3.8-flash (default thinking) | 6.0 s | 6.1 s | 4.2 s | 0.58 s | answers |
| gemini-3.8-flash, thinking `minimal` / `none` | — | — | — | — | 400: level not supported |
| gemini-3.8-flash, thinking `low` | 4.3 s | 7.2 s | 3.4 s | 0.58 s | answers |
| gemini-flash-latest, thinking `low` | 4.9 s | 5.9 s | 2.5 s | 0.29 s | answers |
| gemini-flash-lite-latest, thinking `none` | — | — | — | — | 400: invalid argument |
| gemini-3.5-flash-lite | 3.1 s | 3.5 s | 1.6 s | 0.58 s | answers |
| gemini-3.5-flash-lite + preemptive generation | 2.9 s | 3.1 s | 1.5 s | 0.58 s | **2 of 5 turns silently unanswered** |
| gemini-flash-lite-latest + preemptive | 3.0 s | 3.3 s | 1.4 s | 0.58 s | answers |
| gemini-3.1-flash-lite + preemptive (two runs) | 2.9–3.2 s | 3.4–3.8 s | 1.3 s | 0.58 s | answers |
| … + VAD endpointing 0.3 s | 2.9 s | 3.9 s | 1.3 s | 0.58 s | no gain |
| … + semantic turn detector, 0.3 s | 4.2 s | 7.0 s | 1.7 s | 0.62 s | TTS spikes |
| … + semantic turn detector, 0.5 s | 2.6 s | 2.7 s | 1.1 s | 0.59 s | answers |
| **Chosen configuration, 20 turns** | **3.1 s** | **3.7 s** | **1.19 s (p95 1.42)** | **0.59 s (p95 0.69)** | all 20 answered |

For the chosen configuration, the agent's own stages add up to p50 2.1 s and p95 2.5 s:

- end of turn 0.59 s;
- LLM 1.19 s;
- TTS 0.34 s.

The remaining ~1 s is the silence Silero voice detection waits for before it declares the speech over (about 0.55 s), plus audio transport both ways.

## Decision

- **Development defaults** (`.env.example`):
  - **LLM:** `gemini-3.1-flash-lite`, default thinking, pinned to an exact model version. Moving aliases (`-latest`) and retired models break without warning.
  - **Deepgram:** `nova-3` speech-to-text and `aura-2-thalia-en` voice, with `mip_opt_out` (Deepgram's model-improvement programme) turned off.
  - **Turn-taking:** LiveKit's local multilingual turn detector (`HV_TURN_DETECTION=multilingual`) with a 0.5 s minimum endpointing delay. It waits longer when an answer sounds unfinished, which suits candidates who pause to think.
  - **Preemptive generation:** on. The LLM starts on the interim transcript; this saves about 0.2 s.
- **Privacy:**
  - Interruption detection is pinned to local voice detection (`interruption.mode = "vad"`). LiveKit's "adaptive" mode sends audio to LiveKit Cloud.
  - LiveKit's hosted turn detector (`inference.TurnDetector`) is excluded for the same reason.
  - No interview audio goes to a service without a data-processing agreement.
- **Dispatch reliability:**
  - The worker reports its load as sessions in use ÷ `HV_AGENT_MAX_SESSIONS` (`load.py`). LiveKit's default reports the whole machine's CPU. On a busy PC that made the worker look full, and LiveKit's automatic dispatch then left rooms with no agent, silently and without retrying.
  - Each job ends as soon as its session closes, so the worker is free again at once.

## Consequences

- **The target is missed in development:** p95 3.7 s end-to-end against 2.5 s. SP-09 closes the gap in this order:
  1. **Immediate acknowledgement.** Play a short pre-synthesised "Okay." or "Got it." as soon as the turn ends, while the LLM works. This is master plan §6.8, and it brings perceived latency to about 1 s.
  2. **Deepgram Flux.** Its turn-aware speech-to-text reports end of turn about 0.3 s after speech. It replaces the VAD silence wait and nova-3's finalisation (about 0.5–0.8 s together).
  3. **Voice-detection tuning.** Silero's `min_silence_duration` goes from 0.55 s down to 0.3–0.4 s, with the semantic turn detector guarding against cutting off pauses.
  4. **Regional endpoints.** Re-measure `production` (OpenAI, Azure OpenAI in India) in the Cloud Migration Plan. The LLM is the largest single stage, and the cloud path to India matters.
- **`gemini-3.5-flash-lite` stays unused** until the silent unanswered turns are understood. SP-09 adds a watchdog that notices a committed turn with no reply and re-prompts.
- **SP-09 production readiness:**
  - Dispatch the interview agent explicitly by name (`CreateDispatch`) rather than automatically.
  - Move metrics from the deprecated `metrics_collected` event to `ChatMessage.metrics`.
  - Pre-import slow modules in `prewarm` (the log shows 100–350 ms event-loop stalls on first use).
  - Run the worker with `lk agent dev` or `start`, because the Python CLI's `dev` mode is deprecated.
- **`hv doctor` limitation:** it lists models, but a listed model can still be unavailable (gemini-2.5-flash is listed yet returns 404). A later `doctor --deep` should make one tiny completion per configured model.
- **Env sync limitation:** `hv env-sync` keeps existing values, so developers with older `.env` files must update `HV_LLM_MODEL_FAST` by hand. The runbook says so.
