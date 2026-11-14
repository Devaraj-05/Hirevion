# AI provider routing: implementation plan

**Goal:** Route the `dev` profile's AI calls by task, following the product owner's 2026-11-14 decision: OpenRouter handles resume parsing and screening, NVIDIA Nemotron handles interview questions and evaluation, and Deepgram handles speech. The decision is recorded in [ADR-0034](../../architecture/adr/0034-ai-routing-openrouter-nemotron.md).

**Architecture:**
- `hirevion_core.ai.routing` maps the first part of `AiContext.purpose` to one of two routes:
  - the screening route: `jd`, `resume`, `screening`;
  - the interview route: `questions`, `interview`, `evaluation`.
- `PurposeRouter` sends each call to that route's `OpenAICompatible` backend.
- Each backend is built from an `Endpoint`, which holds the provider's key, base URL, models, how it takes a JSON schema, extra request fields, and the name of its output-cap parameter.

**Global constraints:**
- Keys live only in the root `.env`.
- Errors carry the HTTP status, never the response body.
- Development uses synthetic data only.
- `production` and `mock` behave as before.
- Prices are recorded only with a cited source.

## Tasks

- [x] **1. Routing.** `route_for` and `PurposeRouter`. Tests: all 11 areas map to a route, an unknown area raises, and a source scan finds no purpose without a route.
- [x] **2. Settings and endpoints.**
  - Route providers, keys, base URLs and models (`HV_AI_*_PROVIDER`, `HV_OPENROUTER_*`, `HV_NEMOTRON_*`).
  - Key names are read in any case.
  - NVIDIA receives its schema as `guided_json`.
  - OpenRouter requests carry `require_parameters` and `data_collection: deny`.
  - Wire tests use respx to check each provider's request shape, its `Authorization` header and its `ai_invocations` rows.
- [x] **3. Output cap.**
  - `HV_LLM_MAX_OUTPUT_TOKENS` (default 16,384) is sent on every chat call: as `max_completion_tokens` for OpenAI and as `max_tokens` for the other providers.
  - Wire tests check the parameter for both forms.
  - The cap fixes OpenRouter's 402, which came from reserving 65,536 output tokens.
- [x] **4. Wiring.**
  - `build_ai` builds one backend per provider (two in the default `dev` profile).
  - Embeddings, OCR and vision use the screening route's provider.
  - `aclose` closes each backend once.
  - The interview agent no longer has its own LLM settings.
- [x] **5. Developer tools.**
  - `hv doctor` checks OpenRouter (`GET /api/v1/key`, which spends nothing) and Nemotron (a one-token chat).
  - `hv env-sync` and the required-key check match key names in any case.
  - `.env.example` documents the new keys and models.
- [x] **6. Prices.** The three default OpenRouter models are added from OpenRouter's public model list (retrieved 2026-11-14). A test fails if any default screening-route model has no price.
- [x] **7. Live checks** (`--live`). OpenRouter and Nemotron each return structured answers on the fast and strong tiers. OpenRouter's embeddings and page reading also pass. The vision default changed to `gpt-5-mini` after `gpt-5.4-nano` misread the OCR word in 3 of 4 runs.
- [x] **8. Documentation.** ADR-0034, the runbook's AI section, the threat model, MASTER §5.3 and Appendix A row 78, and the tracking documents.

## Verification

- Unit, wire and devcli tests: `uv run pytest -q backend/core/tests -k ai` and `uv run pytest -q tools/devcli`.
- Live checks: `uv run pytest --live backend/core/tests/live -k "openrouter or nemotron"`.
- Merge gate: `bash scripts/ci-local.sh --all`.
