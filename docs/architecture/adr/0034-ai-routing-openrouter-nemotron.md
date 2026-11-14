# ADR-0034: Development AI routed by task: OpenRouter screens, NVIDIA Nemotron interviews

- **Status:** Accepted (supersedes [ADR-0003](0003-gemini-for-development.md)'s choice of Gemini for development; production stays OpenAI + Deepgram)
- **Date:** 2026-11-14
- **Sub-project:** SP-01 (the AI provider layer, PRD §78)

## Context

- ADR-0003 made Gemini the `dev` profile's LLM, embeddings and vision. The Gemini key has been invalid since 2026-10-03, so every run used the `mock` profile and no real model checked screening or interviews.
- **Product-owner decision, 2026-11-14:** two new keys, `OPENROUTER_API_KEY` and `NEMOTRON_API_KEY` (an NVIDIA build.nvidia.com key). OpenRouter handles resume parsing and screening; Nemotron handles the interview questions and the evaluation. Deepgram keeps speech.
- Live checks on 2026-11-14 found:
  - NVIDIA's hosted endpoint answers `response_format: json_schema` with empty content and rejects `nvext.guided_json` (400). Only a top-level `guided_json` field works.
  - With no output cap, OpenRouter reserves credit for the model's whole output (65,536 tokens). When the balance is lower, it refuses the call (402).
  - `openai/gpt-5.4-nano` misread a rendered test word in 3 of 4 runs. `openai/gpt-5-mini` read it correctly 3 times out of 3.

## Decision

- **Routes.** In `dev`, the first part of each call's `AiContext.purpose` picks the route:
  - **Screening route:** `jd`, `resume`, `screening`. Default provider: OpenRouter.
  - **Interview route:** `questions`, `interview`, `evaluation`. Default provider: NVIDIA Nemotron.
  - An unknown area raises an error. A test scans the code and fails if any purpose has no route.
- **Shared services.** Embeddings, page reading (OCR) and vision always use the screening route's provider.
- **Configuration.**
  - `HV_AI_SCREENING_PROVIDER` and `HV_AI_INTERVIEW_PROVIDER` choose each route's provider: `openrouter`, `nemotron`, `gemini` or `openai`.
  - When both routes name the same provider, one client serves both.
- **Default models.** Each can be changed with `HV_OPENROUTER_*` or `HV_NEMOTRON_*`.

  | Provider | Fast | Strong | Vision | Embeddings |
  |---|---|---|---|---|
  | OpenRouter | `openai/gpt-5.4-nano` | `openai/gpt-5-mini` | `openai/gpt-5-mini` | `openai/text-embedding-3-small` (1,536-d) |
  | Nemotron | `nvidia/nemotron-3.5-lightning-30b-a3b` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | — | — |

- **Structured answers.**
  - OpenRouter, OpenAI and Gemini get a strict `response_format` JSON schema; NVIDIA gets a top-level `guided_json`.
  - OpenRouter requests also send `provider: {require_parameters: true, data_collection: "deny"}`.
  - Pydantic validation and its one repair retry are unchanged.
- **Output cap.** Every chat call sends `HV_LLM_MAX_OUTPUT_TOKENS` (default 16,384, reasoning included). OpenAI takes it as `max_completion_tokens`; the other providers take it as `max_tokens`.
- **Keys.**
  - Required locally: `OPENROUTER_API_KEY`, `NEMOTRON_API_KEY` and `DEEPGRAM_API_KEY`. Names may be in any case, e.g. `nemotron_API_KEY`.
  - Optional locally: the Gemini and OpenAI keys.
  - `hv doctor` checks OpenRouter through `GET /api/v1/key`, which spends nothing, and Nemotron with a one-token chat. It never prints a key or the key's label.
- **Other profiles.** `production` (OpenAI + Deepgram) and `mock` are unchanged.

## Consequences

- **What this enables.** Screening and interviews can run on real models again. The interview agent already reaches its LLM through `hirevion_core`'s services, so its interview turns go to Nemotron with no agent-specific settings.
- **Cost.**
  - OpenRouter's three default models are priced in `prices.yaml`, so their calls count against the organisation's monthly budget.
  - NVIDIA's hosted Nemotron publishes no per-token price. Its calls record `cost_usd = NULL`, so the budget does not count them.
- **Quality.**
  - Prompts and rubrics were tuned only against the mocks. Re-run the screening and interview evaluation sets and SP-10's gate on these routes before trusting scores.
  - The voice benchmark (p95 ≤ 2.5 s to first audio) must be re-measured with Nemotron.
- **Embeddings.**
  - Vectors made by `text-embedding-3-small` are not comparable with the mock's or Gemini's.
  - Stored vectors do not record their model yet (§5.3 assumed they would). After switching providers, re-process the documents and job descriptions before trusting the semantic factor.
- **Data.**
  - OpenRouter, the upstream providers it routes to, and NVIDIA become processors of what they are sent.
  - `data_collection: "deny"` limits OpenRouter to providers that do not store or train on prompts, but it is not a DPA.
  - Development stays on synthetic data until DPAs are signed (§17, MASTER §5.3).
