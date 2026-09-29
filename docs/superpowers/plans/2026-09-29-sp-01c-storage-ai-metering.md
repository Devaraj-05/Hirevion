# SP-01c Storage, AI Provider Layer and Metering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish SP-01 with three foundations:
- blob storage laid out as PRD §85, with short-lived signed URLs;
- the AI provider layer: the six services behind one interface in the `dev`, `production` and `mock` profiles, every call recorded in `ai_invocations` (PRD §79);
- usage metering with per-organisation AI budgets.

**Architecture:**

- **`hirevion_core.storage`** wraps the Azure Blob API (Azurite locally).
  - Paths are built only through typed helpers that start with the organisation id.
  - The signer issues per-blob SAS URLs: write-only for 15 minutes to upload, read-only for 5 minutes to play back.
  - URLs use the public endpoint (`https://storage.hirevion.localhost` locally); the server uses the internal one.
- **`hirevion_core.ai`** defines the services as protocols, with three backends:
  - an OpenAI-compatible backend (LLM, embeddings, vision, OCR). It uses the OpenAI SDK, pointed at Gemini's OpenAI endpoint in `dev` and at OpenAI in `production`;
  - a Deepgram backend (speech-to-text and text-to-speech over REST);
  - a deterministic `mock` backend.

  A `Recorder` writes each call's `ai_invocations` row and its `usage_events` in their own short transaction. The spend survives even when the caller's transaction rolls back. A budget guard refuses calls once an organisation's monthly AI spend reaches its quota.
- **`hirevion_core.metering`** records `usage_events` and sums them; every service will use it (master plan §11).

**Tech Stack:**
- `azure-storage-blob` 12.30 (asyncio, with aiohttp), `openai` 2.54, httpx (Deepgram), PyYAML (the price book).
- Tests: respx (HTTP-level provider contract tests) and pytest; the `live` marker runs opt-in checks against the real vendors.

## Global Constraints

- Everything in `MASTER_IMPLEMENTATION_PLAN.md` §13 and ADR-0002, 0003, 0009 and 0010 applies:
  - model names live in configuration, never in code;
  - keys live only in the root `.env`;
  - embeddings are 1,536-dimensional in both profiles, and every stored vector records its model;
  - every AI call is recorded with model and version, prompt, rubric and evaluation versions, timestamp, input references and output (§79), plus tokens, latency and cost.
- Development uses synthetic data only; nothing in tests or fixtures is real personal data.
- CI never calls a paid API: provider contract tests run against `mock` and against recorded HTTP shapes (respx). The `live` tests run only on request (`uv run pytest -m live`).
- Storage paths always start with the organisation id. A URL for one organisation's blob is never signed in another organisation's context.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/core/src/hirevion_core/storage/paths.py` | `BlobPath` and the §85 builders (`job_blob`, `candidate_blob`, `interview_blob`) |
| `backend/core/src/hirevion_core/storage/service.py` | `StorageSettings`, `StorageService` (put/get/delete/exists, `upload_url`, `download_url`), `ensure_storage()` |
| `backend/core/src/hirevion_core/metering.py` | `record_usage()`, `usage_totals()` |
| `backend/core/src/hirevion_core/ai/types.py` | `AiContext`, result types, errors, service protocols |
| `backend/core/src/hirevion_core/ai/settings.py` | `AiSettings` (profile, keys, models, budget) |
| `backend/core/src/hirevion_core/ai/prices.py`, `prices.yaml` | `PriceBook`: USD per unit, each price with its source and date |
| `backend/core/src/hirevion_core/ai/recorder.py` | `Recorder`: budget check, `ai_invocations` row, usage events |
| `backend/core/src/hirevion_core/ai/openai_compat.py` | LLM (structured output + one repair retry), embeddings, vision, OCR |
| `backend/core/src/hirevion_core/ai/deepgram.py` | Speech-to-text (`/v1/listen`) and text-to-speech (`/v1/speak`) |
| `backend/core/src/hirevion_core/ai/mock.py` | Deterministic services for CI and load tests |
| `backend/core/src/hirevion_core/ai/__init__.py` | `AiServices` and `build_ai(settings, db)` |
| `backend/core/src/hirevion_core/models/{ai_invocation,quota}.py` | ORM models |
| `backend/migrations/versions/0005_ai_invocations_and_quotas.py` | The tables |
| `tools/devcli/src/hirevion_devcli/cli.py` | `hv storage-init` |
| `.github/workflows/ci.yml` | Azurite for the `db` tests |
| `docs/architecture/adr/0011-storage-ai-metering.md` | The decisions |

---

### Task 1: Blob storage and signed URLs

**Interfaces:**

- Produces:
  - `BlobPath(organization_id: UUID, key: str)`. Its `str()` is `"{org}/{key}"`.
  - Builders:
    - `job_blob(org, job_id, filename)`;
    - `candidate_blob(org, candidate_id, filename)`;
    - `interview_blob(org, interview_id, kind: InterviewArtifact, filename)`.
  - `InterviewArtifact = Literal["screen", "camera", "audio", "third-eye", "evidence", "transcript", "report"]`.
  - `StorageSettings`: `azure_storage_account`, `azure_storage_key`, `azure_storage_container = "hirevion"`, `azure_storage_endpoint` (internal), `storage_public_endpoint`.
  - `StorageService(settings)`:
    - `put(path, data, content_type)`, `get(path) -> bytes`, `exists(path) -> bool`, `delete(path)`;
    - `upload_url(org, path, expires=timedelta(minutes=15)) -> str`;
    - `download_url(org, path, expires=timedelta(minutes=5), filename=None) -> str`;
    - `aclose()`.
  - `ensure_storage(settings, allowed_origins) -> None`: a private container, plus CORS for browser uploads.
  - `hv storage-init`.

- [x] Tests first:
  - Pure:
    - builders produce `"{org}/interviews/{id}/screen/seg-000001.mp4"`, and so on;
    - unsafe filenames (`..`, `/`, `\`, empty, over 200 characters, control characters) and unknown artifact kinds raise `ValueError`;
    - signing for another organisation raises `ValueError`;
    - SAS parameters: an upload URL has `sp=cw` and an expiry at most 15 minutes ahead, and a download URL has `sp=r` and at most 5 minutes. Both use the public endpoint.
  - Against Azurite (`db` marker):
    - `put`/`get`/`exists`/`delete` round-trip;
    - an httpx `PUT` to an upload URL (`x-ms-blob-type: BlockBlob`) stores the blob, and a `GET` on that same URL is refused (403);
    - a download URL reads it back, with `Content-Disposition` when a filename is given;
    - a URL signed to expire in the past is refused;
    - `ensure_storage` is idempotent, and the container isn't public (an anonymous `GET` is refused).
    - Azurite honours CORS rules: an `OPTIONS` preflight from `https://app.hirevion.localhost` for `PUT` is allowed. If Azurite ignores service CORS, record that in the ADR and mark the test `xfail(strict=True)` with the reason.
- [x] Implement with `azure.storage.blob.aio` and `generate_blob_sas`:
  - HTTPS-only SAS except when the public endpoint is `http://`;
  - `content_disposition` is set on download SAS;
  - the path's organisation must equal the `org` argument.
  - Dependencies: `azure-storage-blob>=12.30` and `aiohttp` for core.
- [x] `hv storage-init` calls `ensure_storage` with the web origins (`https://app.hirevion.localhost`, `https://candidate.hirevion.localhost`, `https://eye.hirevion.localhost`).
- [x] CI's python job starts Azurite with `docker run`: the account key is generated in the step, the image is pinned by the same digest as `compose.yaml`, and the step exports `AZURE_STORAGE_*`.
- [x] Commit `feat(core): add blob storage with signed upload and download URLs`.

### Task 2: AI foundation — context, recording, budgets, metering, mock

**Interfaces:**

- Produces:
  - `record_usage(session, organization_id, meter, quantity: Decimal, unit, source, attributes=None, occurred_at=None) -> None`.
  - `usage_totals(session, organization_id, since, until) -> dict[str, tuple[Decimal, str]]`, keyed by meter, with the unit.
  - `AiContext(organization_id: UUID, purpose: str, prompt_version: str | None = None, rubric_version: str | None = None, evaluation_version: str | None = None, input_refs: Mapping[str, str] = {})`.
  - Results:
    - `LlmResult[T](value: T, model: str, input_tokens: int, output_tokens: int)`;
    - `Embeddings(vectors: list[list[float]], model: str, input_tokens: int)`;
    - `Transcript(text: str, words: list[Word], duration_seconds: float, model: str)`;
    - `SpeechAudio(audio: bytes, content_type: str, characters: int, model: str)`;
    - `VisionResult[T]`, and `OcrPage(text: str, confidence: float, model: str)`.
  - Errors: `AiError` → `AiUnavailable` (retryable), `AiRequestError` (not retryable), `AiOutputInvalid`, `AiBudgetExceeded`.
  - Service protocols:
    - `LLMService.complete(ctx, messages, schema: type[T], tier="strong") -> LlmResult[T]`;
    - `EmbeddingService.embed(ctx, texts) -> Embeddings`;
    - `SpeechToTextService.transcribe(ctx, audio: bytes, content_type, keyterms=()) -> Transcript`;
    - `TextToSpeechService.synthesize(ctx, text) -> SpeechAudio`;
    - `VisionService.analyze(ctx, image: bytes, content_type, instruction, schema) -> VisionResult[T]`;
    - `OCRService.read_page(ctx, image: bytes, content_type) -> OcrPage`.
  - `AiSettings` (`HV_AI_*` plus the vendor keys):
    - `profile: Literal["dev", "production", "mock"]` (default `dev`);
    - `llm_model_fast`, `llm_model_strong`, `embedding_model`, `vision_model`, `stt_model`, `tts_voice`;
    - `embedding_dimensions = 1536`;
    - `monthly_budget_usd = Decimal("50")`, the default when an organisation has no quota row.
  - `PriceBook.load()` and `PriceBook.cost(service, model, *, input_tokens=0, output_tokens=0, seconds=0, characters=0) -> Decimal | None`.
  - `Recorder(db, prices, settings).call(ctx, service, provider, model, run: Callable[[], Awaitable[R]], usage: Callable[[R], Usage], output: Callable[[R], Any]) -> R`.
  - `build_ai(settings, db) -> AiServices`, which has `llm`, `embeddings`, `stt`, `tts`, `vision` and `ocr`.

- [x] Tests first (DB-marked, mock profile):
  - **Every service records an `ai_invocations` row** with: service, purpose, provider `mock`, model, versions, `input_refs`, `output` (structured for LLM and vision; `{"dimensions": n, "count": k}` for embeddings; `{"characters": n}` for text-to-speech; the transcript text for speech-to-text), tokens/seconds/characters, `latency_ms >= 0`, `status "ok"` and `trace_id`.
  - **Usage events** `ai.llm.input_tokens`, `ai.llm.output_tokens`, `ai.embedding.tokens`, `ai.stt.seconds`, `ai.tts.characters`, `ai.vision.*` and `ai.cost.usd` are recorded with the same `source` (the purpose).
  - **A failing call** (the mock raises `AiUnavailable`) still records a row: `status "error"`, `error_code "unavailable"`, zero cost.
  - **The recording survives the caller's rollback:** call inside a tenant transaction that then raises, and the row still exists.
  - **The budget:**
    - with `quotas(meter="ai.cost.usd", period="month", limit=0.01)` and recorded spend of 0.02, the next call raises `AiBudgetExceeded` before the backend runs (the mock counts calls) and records no row;
    - with no quota row, `monthly_budget_usd` applies.
  - **Tenancy:** tenants can't read each other's invocations, and the app role can't update or delete them.
  - **Pure tests:**
    - `PriceBook.cost` for known models (tokens per million, seconds per minute, characters per thousand);
    - an unknown model gives `None`;
    - every price entry has a `source` URL and a `retrieved` date;
    - the mock is deterministic (the same text gives the same embedding, of `embedding_dimensions` length).
  - **`usage_totals`** sums per meter within the window.
- [x] Migration `0005_ai_invocations_and_quotas`:
  - **`ai_invocations`**, partitioned monthly on `occurred_at`, with a DEFAULT partition:
    - columns: `id`, `occurred_at`, `organization_id`, `service`, `purpose`, `provider`, `model`, `model_version`, `prompt_version`, `rubric_version`, `evaluation_version`, `input_refs jsonb`, `output jsonb`, `input_tokens`, `output_tokens`, `audio_seconds numeric`, `characters`, `latency_ms`, `cost_usd numeric`, `status`, `error_code`, `trace_id`;
    - index `(organization_id, occurred_at)`;
    - RLS; app role `SELECT` and `INSERT`.
  - **`quotas`**:
    - columns: `organization_id`, `meter`, `period` (`month`), `limit_value numeric`, `updated_at`;
    - PK `(organization_id, meter, period)`;
    - RLS; app role `SELECT` only (SP-22 administers quotas).
  - Add `ai_invocations` to `PARTITIONED_TABLES`.
- [x] `prices.yaml`: fetch current prices from the vendors' pricing pages at implementation time, for the configured `dev` and `production` models, embeddings and Deepgram Nova-3 / Aura-2. Record `source` and `retrieved: 2026-09-29` per entry. Don't guess a price: a model without a verified price stays out, and its calls record `cost_usd = NULL`.
- [x] Commit `feat(core): add the AI provider foundation with invocation records and budgets`.

### Task 3: OpenAI-compatible backend (LLM, embeddings, vision, OCR)

**Interfaces:**

- Consumes: Task 2's types, `Recorder`, `AiSettings`.
- Produces:
  - `OpenAICompatible(settings, recorder, provider: Literal["gemini", "openai"])`, which implements `LLMService`, `EmbeddingService`, `VisionService` and `OCRService`.
  - `build_ai` wires it for `dev` (base URL `HV_LLM_BASE_URL`, key `GEMINI_API_KEY`) and `production` (the OpenAI default base URL, `OPENAI_API_KEY`).

- [x] Tests first (respx on the base URL; no network):
  - **The LLM request** carries:
    - the tier's model;
    - `response_format: {"type": "json_schema", "json_schema": {"name": <schema title>, "schema": ..., "strict": true}}`;
    - a system message saying untrusted input is data. Callers pass untrusted text only as `{"role": "user"}` content wrapped in `<data>` tags (master plan §9 "LLM safety").
  - **The repair retry:**
    - an invalid JSON reply, then a valid one, gives the parsed model. Two invocation rows are recorded, the first with `status "invalid_output"`;
    - two invalid replies raise `AiOutputInvalid`.
  - **Error mapping:**
    - 429 and 5xx become `AiUnavailable` (after the SDK's own 2 retries, set with `max_retries=2`);
    - 400/401/403 become `AiRequestError`;
    - a timeout (30 s by default, 10 s for the `fast` tier) becomes `AiUnavailable`.
  - **Usage:** tokens come from `usage.prompt_tokens` / `completion_tokens`, and `model_version` from the response's `model`.
  - **Embeddings:**
    - the request sends `dimensions: 1536`;
    - a response with any other length raises `AiOutputInvalid`;
    - batches are split at 100 inputs.
  - **Vision:** the image goes as a `data:` URL content part. OCR asks for `{text, confidence}`, and its `confidence` is clamped to 0–1.
- [x] Live tests (`@pytest.mark.live`, each skipped unless its key is set):
  - one `fast` structured completion;
  - one embedding (length 1536);
  - one vision call on a generated 200×60 PNG with the word "HIREVION" (Pillow isn't a dependency, so the test writes a tiny PNG with `zlib`), which OCR must read back.

  They run against `dev`, and against `production` when `OPENAI_API_KEY` is set.
- [x] Commit `feat(core): add the OpenAI-compatible AI backend for Gemini and OpenAI`.

### Task 4: Deepgram speech backend

**Interfaces:**

- Produces: `Deepgram(settings, recorder)` implementing `SpeechToTextService` (`POST https://api.deepgram.com/v1/listen`) and `TextToSpeechService` (`POST /v1/speak`), wired into both `dev` and `production`.

- [x] Tests first (respx):
  - **Speech-to-text request:** `model=nova-3&smart_format=true&punctuate=true`, `keyterm=` per key term (at most 50), and `Authorization: Token <key>`.
  - **Speech-to-text parsing:**
    - the transcript, words with `start`/`end`/`confidence`, and `duration_seconds` come from `metadata.duration`;
    - the usage meter is `ai.stt.seconds`.
  - **Text-to-speech:**
    - `model=<voice>`, a JSON `{"text": ...}` body, and the audio bytes and content type come back;
    - `characters` is `len(text)`;
    - text over 2,000 characters raises `AiRequestError` (Deepgram's limit) before any call.
  - **Errors:** 429 or 5xx become `AiUnavailable`; 400 or 401 become `AiRequestError`.
- [x] Live tests:
  - synthesize "Hirevion interview check", then transcribe that audio;
  - the transcript must contain "interview".
- [x] Commit `feat(core): add the Deepgram speech backend`.

### Task 5: Docs, CI and finish

- [x] **Configuration:**
  - `.env.example` gains `HV_AI_PROFILE=dev`, `HV_LLM_MODEL_STRONG`, `HV_EMBEDDING_MODEL=gemini-embedding-001`, `HV_VISION_MODEL` and `HV_AI_MONTHLY_BUDGET_USD=50`. The strong and vision model names come from the models the key can list, via `hv doctor`.
  - pytest `addopts` gains `-m "not live"`.
- [x] **ADR-0011:**
  - storage layout and signing;
  - the provider layer's three backends and profiles;
  - recording in its own transaction;
  - budgets;
  - the price book and its sources;
  - live checks;
  - what SP-04 (Tesseract and ClamAV), SP-09 (LiveKit plugins record through `Recorder`) and SP-22 (quota administration, usage pages) build on.
- [x] **Runbook:** `hv storage-init`, `uv run pytest -m live` (costs a few cents), and how to read spend from `ai_invocations`.
- [x] Commit `docs: add ADR-0011 storage, AI provider layer and metering`, then finish the branch: green CI, fast-forward, delete the branch.

## Self-review

- **Spec coverage.** The master plan SP-01 deliverables left after SP-01a and SP-01b:
  - the storage service and URL signer with §85 paths (Task 1);
  - the AI provider layer: six services, the `dev`/`production`/`mock` profiles and `ai_invocations` recording (Tasks 2–4);
  - metering (Task 2).
- **Exit criterion.** "Provider contract tests pass on mock, plus a small opt-in live check against Gemini and Deepgram (and OpenAI when its key is set)" (Tasks 2–4).
- **Handed on:**
  - SP-04: the Tesseract OCR engine (in the worker image, with vision as the low-confidence fallback) and ClamAV scanning on upload.
  - SP-09: the LiveKit plugins' streaming STT/LLM/TTS record through `Recorder`.
  - SP-12: audited playback endpoints over `download_url`.
  - SP-22: quota administration and the usage and cost pages over `usage_totals`.
  - SP-01b's `purge_idempotency_keys` and partition upkeep still need the worker's scheduler.
- **Type consistency:** `AiContext`, `Recorder.call`, `build_ai`, `StorageService.upload_url` / `download_url` and `record_usage` use the same names in every task.

## Implementation notes

Where the build differs from the steps above (ADR-0011 records the reasons):

- **SAS protocol** follows the storage service's own endpoint, not the public one. Behind Caddy, Azurite receives plain HTTP, so an HTTPS-only SAS was refused (`AuthorizationProtocolMismatch`).
- **Azurite `--disableProductStyleUrl`** (compose and CI). Without it Azurite took the account name from `storage.hirevion.localhost`, so every signed URL through Caddy returned 404. `hv smoke` now checks a signed round trip.
- **Embedding model** `gemini-embedding-2`, not `gemini-embedding-001` (ADR-0003 amended). Vectors are always normalised, because 001 returns unnormalised vectors at 1,536 dimensions.
- **Gemini embedding quirks**, found by the live checks: no usage (tokens estimated and flagged) and `index: null` (input order kept).
- **An invalid first reply** is recorded as `status "error"`, `error_code "invalid_output"`, with its tokens. The plan's separate `invalid_output` status isn't needed.
- **Live tests** are enabled with `--live`, not `-m "not live"` in `addopts`, which any later `-m` would silently replace.
- **Default strong model** `gemini-3.8-flash`. The only 3.x Pro is a preview, and previews change or retire without warning.
- **OpenAI chat models** stay out of `prices.yaml` until production chooses them; only `text-embedding-3-large` is priced.
- **Missing keys** fail when the backends are built, naming the variable. The SDK's own message always blamed `OPENAI_API_KEY`.
- **The branch** is `feat/sp-01c-storage-ai`. An automatic commit (not made in this session) had pushed `feat/sp-01c-storage-ai-metering`; that branch is deleted when this one merges.
