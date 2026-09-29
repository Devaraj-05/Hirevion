# ADR-0011: Blob storage, the AI provider layer and metering

- **Status:** Accepted (amends ADR-0003 on the embedding model)
- **Date:** 2026-09-29
- **Sub-project:** SP-01c

## Context

- **Storage.** Recordings, resumes, reports and evidence live in blob storage laid out by PRD §85, and clients reach it only through short-lived SAS URLs.
- **AI.** Every AI feature goes through one provider layer (PRD §78). Each call must be auditable and reproducible from its model, prompt, rubric and evaluation versions, timestamp, inputs and output (PRD §79).
- **Profiles.** ADR-0002 and ADR-0003 fix the vendors: Gemini and Deepgram in development, OpenAI and Deepgram in production, and fakes in CI.
- **Cost.** Every developer run costs money, so spend must be metered from the first call and capped per organisation (master plan §11, D14).

## Decision

- **Storage (`hirevion_core.storage`).**
  - **Layout:** one private container (`hirevion`) whose blob names follow §85 under the organisation id: `{org}/jobs/…`, `{org}/candidates/…`, `{org}/interviews/{id}/{screen|camera|audio|third-eye|evidence|transcript|report}/…`.
  - **Paths:** built only through validating helpers, with safe file names and known artifact kinds.
  - **Signed URLs:**
    - Uploads: write-only (`cw`) for 15 minutes. Downloads: read-only for 5 minutes, optionally as an attachment. One blob per URL.
    - A URL is never signed for a blob outside the caller's organisation.
    - URLs point at the public endpoint (`https://storage.hirevion.localhost` locally). The SAS protocol follows what the storage service itself receives: HTTP behind Caddy locally, HTTPS-only on Azure.
  - **Local stack:**
    - Azurite runs with `--disableProductStyleUrl`. Otherwise it parses the account name out of Caddy's host name and every signed URL through Caddy 404s.
    - `hv storage-init` creates the container and CORS rules for the web origins, which Azurite honours. `hv smoke` proves a signed round trip through Caddy.
- **The AI provider layer (`hirevion_core.ai`).**
  - **Services:** six protocols (LLM, embeddings, speech-to-text, text-to-speech, vision, OCR) with typed results and errors. Callers switch on `AiUnavailable` (retry later), `AiRequestError`, `AiOutputInvalid` and `AiBudgetExceeded`.
  - **Three backends:**
    - **OpenAI-compatible** (LLM, embeddings, vision, OCR): one OpenAI-SDK code path, pointed at Gemini's compatible endpoint in `dev` and at OpenAI in `production`.
      - Answers are strict JSON-schema structured outputs, validated with Pydantic, with one repair attempt.
      - A system message tells the model that tagged input is untrusted data, and `as_data()` wraps and escapes untrusted text.
      - The SDK retries 429s and 5xxs twice.
    - **Deepgram** (speech-to-text on `/v1/listen`, text-to-speech on `/v1/speak`) over plain HTTPS.
    - **Mock:** deterministic outputs and realistic usage; all of CI runs on it.
  - **Configuration:**
    - `HV_AI_PROFILE` picks the backends, and model names come only from settings.
    - `dev` defaults: `gemini-3.1-flash-lite` for fast calls and vision/OCR, `gemini-3.8-flash` for screening and evaluation, `gemini-embedding-2`, Deepgram `nova-3` and `aura-2-thalia-en`.
    - A missing key fails at startup, naming the variable.
  - **Embeddings.**
    - **Model:** `gemini-embedding-2` at 1,536 dimensions replaces ADR-0003's `gemini-embedding-001`. It is on Google's price list, returns unit vectors and recommends 1,536.
    - **Normalisation:** every vector is L2-normalised anyway, because `gemini-embedding-001` returns unnormalised vectors below 3,072 dimensions.
    - **Usage:** Gemini's compatible endpoint reports no token usage for embeddings and sends `index: null`, so usage is estimated (at about 4 characters per token, flagged `estimated`) and order kept.
- **Recording and budgets (`Recorder`).**
  - **Budget check:** before a call reaches the vendor, the organisation's spend this month is compared with its `ai.cost.usd` quota, or `HV_AI_MONTHLY_BUDGET_USD` when it has none.
  - **Record:** after the call, success or failure, one `ai_invocations` row holds:
    - the §79 fields;
    - tokens, audio seconds and characters;
    - latency (including SDK retries), cost, status and trace id.

    Its `usage_events` (`ai.<service>.*`, `ai.cost.usd`) are written in the same transaction.
  - **Isolation:** that transaction is the Recorder's own, so spend is kept when the caller's transaction rolls back.
  - **Tables:** `ai_invocations` is monthly-partitioned, tenant-scoped and insert-only for the app role. `quotas` is read-only to tenants.
- **Prices.**
  - `prices.yaml` holds list prices for the configured models only, each with its source page and the date it was read. It supports prices that change on a date (Gemini 3.x Flash rises on 2027-01-01) and model-family patterns (`aura-2-*`).
  - A model without a verified price records `cost_usd = NULL`: no guesses. OpenAI's chat models are added when production chooses them.
- **Metering (`hirevion_core.metering`).** `record_usage()` and `usage_totals()` over `usage_events`, for every service.
- **Live checks.**
  - `uv run pytest --live backend/core/tests/live` calls the real vendors: structured answers on both tiers, embeddings, OCR of a rendered word, and a speech round trip. The OpenAI checks also run when `OPENAI_API_KEY` and `HV_OPENAI_TEST_MODEL` are set.
  - They're behind a flag rather than `-m`, which a later `-m` on the command line would silently replace.
  - Measured on 2026-09-29 (warm calls): flash-lite about 1 s and `gemini-3.8-flash` about 2 s for a short structured answer; one cold run took 10–15 s, retries included.

## Consequences

- **A new AI feature:**
  - picks a purpose name and versioned prompt/rubric files;
  - passes untrusted text through `as_data()`;
  - handles `AiUnavailable` by retrying later (workers) or degrading (live paths);
  - reads its spend from `ai_invocations`.
- **Recording failures are logged, not raised,** because the vendor call already happened. A DB outage can therefore under-count spend.
- **Handed on:**
  - **SP-04:** the Tesseract OCR engine (with vision as the low-confidence fallback) and ClamAV scanning of uploads.
  - **SP-09:** LiveKit's streaming STT/LLM/TTS plugins record through `Recorder`, with streaming Deepgram prices added.
  - **SP-12:** audited playback endpoints over `download_url`.
  - **SP-22:** quota administration and the usage/cost pages over `usage_totals`.
  - **Worker scheduler:** purging idempotency keys and keeping partitions ahead.
- **Cloud Migration Plan:**
  - Azure Blob with user-delegation SAS (the signer is the one place to change).
  - `AZURE_STORAGE_ENDPOINT` and `STORAGE_PUBLIC_ENDPOINT` set to the account URL (HTTPS-only SAS then follows automatically).
  - Key Vault for the vendor keys.
  - DPAs with Google, OpenAI and Deepgram before any real candidate data.
