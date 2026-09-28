# ADR-0003: Gemini for development and testing, OpenAI for production

- **Status:** Accepted (amends ADR-0002)
- **Date:** 2026-09-28
- **Sub-project:** SP-00a.1

## Context

ADR-0002 put all AI on OpenAI and Deepgram. The product owner then supplied a paid Gemini API key for development and testing, with OpenAI reserved for production. Deepgram stays the speech provider (speech-to-text and text-to-speech) everywhere.

## Decision

- Profiles: `dev` (Gemini + Deepgram) for development and testing, `production` (OpenAI + Deepgram), `mock` for CI and load tests.
- Gemini is called through its OpenAI-compatible endpoint wherever it supports the feature, so one client code path (the OpenAI Python SDK, and LiveKit Agents' `openai` plugin) serves both `dev` and `production`. Native Gemini calls are added only for features the compatible endpoint lacks.
- Embeddings are 1,536-dimensional in both profiles (`gemini-embedding-001` with `output_dimensionality=1536`; `text-embedding-3-large` with `dimensions=1536`). Each stored vector records its model; switching profiles runs the re-embed job.
- Required local keys: `GEMINI_API_KEY`, `DEEPGRAM_API_KEY`. `OPENAI_API_KEY` is optional locally and checked only when set.

## Consequences

- Development spend goes to Gemini; production quality and latency must be re-measured on OpenAI before go-live (the SP-00 benchmark and the eval harness run against both once the OpenAI key is set).
- Prompts and rubrics are evaluated on both providers, because model behaviour differs; the eval harness gates each switch.
- Google's paid tier doesn't use prompts to improve its products; a DPA with Google is still needed before any real candidate data is used.
