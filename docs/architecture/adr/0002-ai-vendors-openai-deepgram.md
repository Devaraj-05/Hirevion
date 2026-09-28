# ADR-0002: OpenAI and Deepgram APIs for all AI, from day one

- **Status:** Accepted; amended by [ADR-0003](0003-gemini-for-development.md) (Gemini for development and testing)
- **Date:** 2026-09-28
- **Sub-project:** SP-00a

## Context

The approved master plan first proposed free local models for development. The product owner has OpenAI and Deepgram API keys and chose to use them instead (2026-09-28). The PRD requires an AI provider abstraction (§78), streaming speech (§33, §42) and auditable AI use (§79).

## Decision

- Profiles: `vendor` (OpenAI for LLM, embeddings, vision and a text-to-speech fallback; Deepgram for streaming speech-to-text and Aura-2 text-to-speech) for development and production, and `mock` (deterministic fakes) for CI and load tests.
- Every AI call goes through `hirevion_core.ai` and is recorded with model, prompt and rubric versions, tokens, latency and cost.
- Model names live in configuration; the SP-00 benchmark picks them from the models the keys can use.
- Keys live only in the gitignored root `.env` (Key Vault in the cloud). Never in the repo, the desktop app or the web bundle.
- Development uses synthetic data. Real candidate data goes to the vendors only after DPAs are signed and retention / model-improvement opt-outs are set.

## Consequences

- Real model quality and latency from the first day; no GPU needed.
- Every developer run costs money: metering and per-organisation budgets are built in from SP-01, and CI uses `mock`.
- Latency depends on the network path from India to the vendors; SP-00 measures it, and fallbacks (Azure OpenAI, OpenAI speech) cover outages.
- ElevenLabs or Cartesia can be added later as text-to-speech providers without code changes outside the provider layer.
