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
- **Fallback (product-owner decision, later on 2026-11-14: "if OpenRouter is not working then use Nemotron").** When the screening provider can't serve a call (`AiUnavailable`: no credit (402), unreachable, rate-limited or failing), the same call goes to `HV_AI_SCREENING_FALLBACK` (default `nemotron`; `none` turns it off). A refusal (a bad request, an answer that doesn't fit the schema, the budget) is not moved: it would fail there too and moving it would hide a bug. Both attempts are rows in `ai_invocations`. This covers answers, vision and page reading.
- **Embeddings.** Every stored vector comes from one provider, `HV_AI_EMBEDDING_PROVIDER` (default `nemotron`, `nvidia/nemotron-3.5-embed-1b` at 1,536 dimensions, sent as `input_type: passage`), never from a fallback: vectors from two models aren't comparable, and stored vectors don't yet record their model. OpenRouter's provider preferences go with its embeddings when it is chosen: they carry resume text.
- **Page reading and vision** use the screening route (with its fallback). Nemotron's vision model is `nvidia/nemotron-3.5-super-vl-120b-a12b`, which read the live check's rendered word in two runs of two.
- **Configuration.**
  - `HV_AI_SCREENING_PROVIDER`, `HV_AI_INTERVIEW_PROVIDER` and `HV_AI_EMBEDDING_PROVIDER` choose `openrouter`, `nemotron` or `gemini`; `HV_AI_SCREENING_FALLBACK` also takes `none`. OpenAI is the production profile (in `dev` it would get Gemini's model names), so the settings refuse it.
  - Each provider gets one client, however many routes use it.
- **Default models.** Each can be changed with `HV_OPENROUTER_*` or `HV_NEMOTRON_*`.

  | Provider | Fast | Strong | Vision | Embeddings |
  |---|---|---|---|---|
  | OpenRouter | `openai/gpt-5.4-nano` | `openai/gpt-5-mini` | `openai/gpt-5-mini` | `openai/text-embedding-3-small` (1,536-d) |
  | Nemotron | `nvidia/nemotron-3.5-lightning-30b-a3b` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | `nvidia/nemotron-3.5-embed-1b` (1,536-d) |

  `nvidia/nemotron-3-ultra-550b-a55b` also answers on NVIDIA's API with the same key (checked 2026-11-14) and can be set as `HV_NEMOTRON_MODEL_STRONG`. On OpenRouter its `:free` variant answers plain chat, but OpenRouter refuses Hirevion's screening requests for it: its only endpoint may train on prompts, which `data_collection: deny` excludes, and it takes no JSON schema.

- **Structured answers.**
  - OpenRouter, OpenAI and Gemini get a strict `response_format` JSON schema; NVIDIA gets a top-level `guided_json`.
  - OpenRouter requests also send `provider: {require_parameters: true, data_collection: "deny"}`.
  - Pydantic validation and its one repair retry are unchanged.
- **Output cap.** Every chat call sends `HV_LLM_MAX_OUTPUT_TOKENS` (default 16,384, reasoning included). OpenAI takes it as `max_completion_tokens`; the other providers take it as `max_tokens`. An answer cut off at the cap (`finish_reason: length`) fails at once with a message naming the setting; a repair under the same cap would be cut off again.
- **Keys.**
  - Required locally: the keys of the providers the routes, the fallback and the embeddings use (by default `OPENROUTER_API_KEY` and `NEMOTRON_API_KEY`), and `DEEPGRAM_API_KEY`. Names may be in any case, e.g. `nemotron_API_KEY`.
  - Optional locally: the Gemini and OpenAI keys.
  - `hv doctor` checks OpenRouter through `GET /api/v1/key`, which spends nothing, and Nemotron with a one-token chat, at the app's base URLs and model. It asks only for the keys the configured routes need, and never prints a key or the key's label.
  - `build_ai` checks every key it needs before it opens any client.
- **Other profiles.** `production` (OpenAI + Deepgram) and `mock` are unchanged.

## Consequences

- **What this enables.** Screening and interviews can run on real models again. The interview agent already reaches its LLM through `hirevion_core`'s services, so its interview turns go to Nemotron with no agent-specific settings.
- **Cost.**
  - OpenRouter's three default models are priced in `prices.yaml`, so their calls count against the organisation's monthly budget.
  - NVIDIA's hosted Nemotron publishes no per-token price. Its calls (embeddings and fallbacks included) record `cost_usd = NULL`, so the budget does not count them.
  - With no OpenRouter credit, screening runs on Nemotron through the fallback, each call first refused by OpenRouter (402) at no cost.
- **Quality.**
  - Prompts and rubrics were tuned only against the mocks. Re-run the screening and interview evaluation sets and SP-10's gate on these routes before trusting scores.
  - The voice benchmark (p95 ≤ 2.5 s to first audio) must be re-measured with Nemotron.
- **Embeddings.**
  - Vectors from NVIDIA's embedding model are not comparable with the mock's, Gemini's or OpenRouter's.
  - Stored vectors do not record their model yet (§5.3 assumed they would). After switching providers, re-process the documents and job descriptions before trusting the semantic factor.
- **Data.**
  - OpenRouter, the upstream providers it routes to, and NVIDIA become processors of what they are sent. NVIDIA receives resume text for every embedding, and screening calls whenever OpenRouter can't serve.
  - `data_collection: "deny"` limits OpenRouter to providers that do not store or train on prompts, but it is not a DPA.
  - Development stays on synthetic data until DPAs are signed (§17, MASTER §5.3).
