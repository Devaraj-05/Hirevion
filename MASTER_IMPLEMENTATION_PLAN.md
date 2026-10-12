# Hirevion — Master Implementation Plan

> **For agentic workers:** This is the master implementation plan: architecture spec, PRD review, sub-project breakdown, schedule and PRD traceability.
> - Before each sub-project (SP-xx) starts, write its detailed TDD task plan with `superpowers:writing-plans`, saved to `docs/superpowers/plans/YYYY-MM-DD-sp-xx-<name>.md`.
> - Execute it with `superpowers:subagent-driven-development` (or `superpowers:executing-plans`).
> - PRD = `AI_Recruitment_Platform_Complete_PRD.md`, cited as §n. Appendix A maps every PRD section to the sub-project that delivers it.

---

## 0. Context

- **Repository today:**
  - Greenfield: the repo holds only the PRD, in one commit. Remote: `github.com/Devaraj-05/Hirevion`.
  - The repo-local git identity is `Devaraj-05 <padma.devaraj1800@gmail.com>`. The *global* git config uses a different work identity, so the local pin must never be bypassed.
- **Goal:** build the complete PRD — two separate applications plus the supporting pieces:
  1. The **Recruitment Platform** web application, which controls and manages everything.
  2. The **Candidate Windows Desktop AI Interview** (`AI-Interview.exe`), which candidates install and log into to take the AI interview.
  3. **Third-Eye**, a mobile-browser camera.
  4. The **shared backend**.
- **Where it runs:** everything runs end-to-end locally on Docker Desktop. AI runs on hosted APIs through your keys (decided 2026-09-28, replacing the earlier local-model idea): Gemini for development and testing, OpenAI in production, Deepgram for speech. Everything else is free and local.
  - The move to Azure (Central India) is a separate **Cloud Migration Plan** written after the local build.
  - That move must be configuration plus deployment, not a rewrite.
- **Decisions made with you:**
  - You build solo with Claude Code.
  - Nothing is reused; everything is built from scratch.
  - **No PRD feature is skipped.**
  - Security, robustness and usability are non-negotiable.
  - Recruiter identity is built in-house, following your answer "build everything locally first".
  - AI vendors: Gemini (your paid key) for LLM, embeddings and vision in development and testing; OpenAI for the same in production; Deepgram for speech-to-text and text-to-speech in both. ElevenLabs/Cartesia stay optional text-to-speech upgrades for later.
  - Customers and data are in India, so the DPDP Act 2023 applies.
  - Launch is full GA with internal security testing, followed by an external pentest.
- **Git hygiene:** commits and pushes go out only as Devaraj-05, with no Claude attribution anywhere (§13 and CLAUDE.md).
- **This file** becomes `MASTER_IMPLEMENTATION_PLAN.md` at the repo root. It's committed and reviewed by you **before any implementation starts** (§17).

## 1. The two applications and their boundaries (§5, §109)

| Piece | Who uses it | Responsibility | Delivered as |
|---|---|---|---|
| **Recruitment Platform (web)** | Super Admin, Org Admin, Recruiter, Hiring Manager, Interviewer/Reviewer | Control, configuration, screening, candidates, live monitoring, reviews, reports, analytics, administration, integrations | Next.js web app. It also hosts the **candidate portal** on a separate host: invitation acceptance, set password, download, notices, data rights, candidate report. |
| **AI Interview Desktop (Windows)** | Candidate only | Authentication, system check, consent, AI voice interview, coding, camera/mic/screen capture, native Windows proctoring, recording | Signed Tauri 2 `.exe`. Installs per user with no admin rights, auto-updates, x64 + ARM64. |
| **Third-Eye** | Candidate's phone | A temporary second camera angle | A mobile web page opened from a QR code; nothing to install. |
| **Backend** | All of the above | Source of truth, AI orchestration, realtime, storage, evaluation | Containers: `api`, `realtime`, `worker`, `media-worker`, `interview-agent`, `vision-agent`, `coding-service`, `sandbox-runner`. |

The apps share **only** versioned contracts:
- the OpenAPI spec, with a generated TypeScript client;
- event schemas;
- a design-token package.

Each application has its own build, tests and release pipeline.

## 2. Decisions (ADR summary)

| # | Decision | Why |
|---|---|---|
| D1 | One monorepo: pnpm + Turborepo for TypeScript, a uv workspace for Python, a Cargo workspace for Rust. Top-level folder names follow PRD §93. | One CI pipeline and shared contracts. |
| D2 | The backend is a FastAPI modular monolith (`api`) plus `realtime`, `worker` (Valkey-stream consumers, ADR-0015), `media-worker`, `interview-agent`, `vision-agent`, `coding-service` and `sandbox-runner`. PostgreSQL 17 + pgvector; Valkey 8 as the Redis-compatible store. | Follows the §87 service split; the §86 Recruitment/Interview/Proctor APIs become route groups that can be split out later. |
| D3 | Web stack: Next.js (App Router, React 19), TypeScript, Tailwind v4, shadcn/ui, TanStack Query and Table, Zustand, ECharts, next-intl, react-hook-form + zod, and an OpenAPI-generated client. | §94. |
| D4 | Desktop stack: Tauri 2 with React/TS/Vite and Monaco. Native code uses the Rust `windows` crate. MediaPipe Tasks (WASM) runs on-device computer vision. NSIS per-user installer and a signed updater. | §27 and §94. |
| D5 | Self-hosted LiveKit server and Egress in Docker. The voice pipeline runs on LiveKit Agents (Python), with our orchestrator plugged in. | Provides turn detection, barge-in, streaming and fallbacks; serves §52, §65 and §92. |
| D6 | An AI provider abstraction (§78) with three profiles: `dev` (Gemini + Deepgram) for development and testing, `production` (OpenAI + Deepgram), and `mock` (deterministic fakes) for CI and load tests. Providers and models are set per route in configuration. | Real model quality and latency from day one, no GPU needed, and the cost model measures real spend. |
| D7 | In-house identity:<br>• **Recruiters:** argon2id passwords, TOTP and passkeys, sessions, lockout, SSO (Entra ID/OIDC/SAML) and SCIM.<br>• **Candidates:** invitation → set password → desktop login (plus an email OTP on a new device, org-configurable) → device-bound DPoP tokens. | Your choice; also delivers §8 device and session binding. |
| D8 | Storage uses the Azure Blob API everywhere (Azurite locally), behind a storage-service and URL-signer interface. ClamAV scans files. Email goes over SMTP (Mailpit locally). | The cloud move needs no rework. |
| D9 | The coding sandbox is a separate `sandbox-runner` that starts a fresh, hardened container for every run and destroys it afterwards. | §46. |
| D10 | Recording:<br>• **Screen:** native Rust capture of every display → Media Foundation H.264 → 10-second MP4 segments.<br>• **Camera and mic:** WebCodecs segments.<br>• **Server-side copies** of the conversation audio and the third-eye video.<br>• **All segments** go to an encrypted local queue → resumable upload → server acknowledgement. | §50, §51 and §95. |
| D11 | Proctoring is evidence-first. On-device computer vision is checked by server-side verification. Media state the server observes is the ground truth. | The client cannot be trusted. |
| D12 | Realtime fan-out uses Redis Streams rather than Pub/Sub. A transactional outbox carries every domain event. | Alerts and webhooks are never lost. |
| D13 | OpenTelemetry sends traces, metrics and logs to a Grafana LGTM stack. GlitchTip (Sentry-compatible) collects errors and crashes. | Free, and portable to the cloud. |
| D14 | Usage metering is built in from SP-01 and feeds a cost model. | Supports your goal of estimating the total cost before moving to the cloud. |

## 3. Architect's review of the PRD

### 3.1 Strong — keep as is

- **Clean boundaries (§109):**
  - The web app is the control plane.
  - The desktop handles capture and the interview.
  - The backend is the source of truth.
  - Third-eye is temporary.
- **Responsible design:**
  - Humans keep authority over hiring decisions.
  - Every score has evidence behind it.
  - There is no single "cheating score" (§2, §68).
- **Sound engineering choices:**
  - Start as a modular monolith and split later (§87).
  - Version interview templates (§80).
  - Record AI governance metadata (§79).
  - Record in segments with recovery (§50–51).
  - Ship no master credentials in the desktop (§8).

### 3.2 Gaps & corrections (all folded into this plan)

1. **Responsible AI (missing):**
   - Blind screening before any LLM scoring. The redaction list includes India-typical resume "Personal Details" fields:
     - name, photo, gender, DOB/age
     - marital status, religion/caste cues, father's name
     - address below city level
   - Mask Aadhaar and PAN numbers when storing them.
   - Adverse-impact monitoring using the four-fifths rule, based on voluntary self-ID data stored separately.
   - Never infer emotion or personality. Prosody stays descriptive and unscored; EU AI Act Article 5 prohibits workplace emotion inference, which matters if you expand.
   - No automatic rejection.
   - Tell candidates AI is used, and let them request an accommodation or an alternative process.
2. **DPDP Act 2023 + DPDP Rules 2025 (missing):**
   - An itemised notice to candidates.
   - Consent recorded per purpose and per notice version, with withdrawal.
   - Data-principal rights: access, correction, erasure, grievance and nomination.
   - A 72-hour breach runbook.
   - Processing logs kept for at least one year.
   - The employer is the Data Fiduciary and Hirevion is the Data Processor, so both a DPA and a sub-processor register are needed.
   - Explicit consent for face and voice analysis, which may count as biometric data under the IT Act's SPDI rules.
3. **Adversarial inputs:**
   - Detect prompt-injection in resumes: white, tiny, off-page or metadata text.
   - Keep spoken injection attempts isolated from the evaluator.
   - Machine-verify every evidence quote against the source text.
4. **Modern cheating vectors missing from §55.** New evidence events:
   - `CAPTURE_EXCLUDED_WINDOW` — a window hidden from capture via `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, which is how AI "interview copilot" overlays hide.
   - `REMOTE_SESSION_DETECTED`.
   - `VIRTUAL_DEVICE_DETECTED`.
   - `VM_DETECTED` — evidence only, because Hyper-V/VBS produce false positives.
   - `ADDITIONAL_SPEAKER_DETECTED`.
   - `TELEMETRY_GAP`.
   - `CLIENT_INTEGRITY_WARNING` — a debugger, WebView2 debugging variables such as `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`, or a tampered binary.
   - Plus INFO lifecycle events (`*_RECONNECTED`, `SESSION_INTERRUPTED`/`RESUMED`), as implied by the §64 examples.
5. **The client cannot be trusted:**
   - Device-bound proof-of-possession keys (TPM-backed where available) implement the §8 binding.
   - Telemetry is signed and sequenced, so gaps can be detected.
   - Camera, screen and third-eye status come from LiveKit and upload state the server observes, not only from what the client reports.
6. **Interview continuity:**
   - §51 recovers recordings but not the interview itself.
   - Add a session-resume policy: grace window, maximum interruptions, timer-pause rules.
   - Recover from an agent crash using per-turn checkpoints.
7. **Turn-taking:** candidates in technical interviews pause to think.
   - Use semantic end-of-turn detection with tolerance for long pauses.
   - Give candidates "Done answering", "Repeat" and "Need a moment" controls.
   - Provide a text-answer mode as an accommodation (§90 `POST /interviews/{id}/answer`).
   - The AI never cuts a candidate off.
8. **Architecture corrections:**
   - Replace Pub/Sub with Redis Streams, resuming from the last event ID.
   - Add a transactional outbox.
   - Add composite tenant foreign keys plus Postgres row-level security.
   - Partition the high-volume tables monthly.
   - pgvector's HNSW index caps at 2,000 dimensions, so embeddings are 1,536-dimensional (supported natively by both Gemini and OpenAI embedding models), with a re-embed job for provider changes.
   - The linear §35 flow conflicts with adaptive difficulty (§39). Keep the §35 states, but run EASY→MEDIUM→HARD as a per-skill ladder adjusted by `DifficultyController`.
   - Synchronise all event clocks to server time.
9. **Notes for the Cloud Migration Plan:**
   - LiveKit needs UDP, which Azure Container Apps cannot provide, so use LiveKit Cloud or VMs/AKS.
   - Azure Cache for Redis is being retired; use Azure Managed Redis.
   - Kong isn't needed at launch; Front Door WAF plus in-app rate limits are enough.
10. **Licensing hazards:**
    - Avoid PyMuPDF (AGPL), Ultralytics YOLO (AGPL) and Coqui XTTS (non-commercial).
    - Use pdfplumber/pypdfium2 and Apache-2.0 detectors (RT-DETR/D-FINE) instead.
    - License scanning runs in CI.
11. **Windows realities:**
    - SmartScreen reputation builds over time; EV certificates no longer bypass it.
    - Windows "N" editions lack Media Foundation, so the system check guides candidates to the Media Feature Pack.
    - Installs are per-user, for both x64 and ARM64.
    - Candidates with several monitors: capture every display, or enforce a single display by policy.
    - Bandwidth is variable: throttle uploads and finish them after the interview.
    - Recover from power or network loss.
12. **Missing product pieces:**
    - A candidate portal.
    - Reschedule and support requests.
    - Usage metering, quotas and cost tracking per tenant.
    - An AI evaluation harness, calibrated against human raters.
    - A bias-audit export.
    - Feature flags.
    - A desktop release registry: minimum supported version and staged rollout (§26/§28 version check).
    - A proctor-event review outcome ("confirmed" vs "false positive"), which the §106 false-positive-rate KPI needs.
13. **Workspace interpretation (§32):**
    - Coding questions use Monaco.
    - System-design questions use a whiteboard (Excalidraw, MIT); its snapshot goes into the evaluation.
    - All other questions show a question card and notes.

## 4. Scope boundaries

- **Out of scope (§4):**
  - Payroll, attendance, post-hire HRMS, benefits.
  - General HR case management.
  - Autonomous hiring decisions.
  - Unexplained single "cheating scores".
  - A native mobile third-eye app.
  - Unnecessary global keystroke recording.

  The optional shortcut suppression never records keys.
- **Deferred to the Cloud Migration Plan** (by your instruction):
  - The §88 Azure production architecture.
  - The Azure part of §94.
  - Cloud-scale load tests (1,000 → 10,000+ concurrent interviews, §100).
  - Cloud backup/DR.
  - Production code-signing certificate usage.
  - WAF/CDN setup.

  This plan builds everything so that those steps are configuration plus deployment.

## 5. Local-first architecture

### 5.1 Topology

```
Windows 11 host
├─ recruitment-platform (Next.js dev :3000)    ├─ third-eye (Vite dev :5174)    ├─ ai-interviewer-desktop (Tauri)
│        │                                                                      phone (same Wi-Fi) ─► cloudflared quick tunnel (HTTPS)
▼        ▼
Caddy (TLS via local CA) *.hirevion.localhost   ← local "API gateway" (§86)
  app.        /api/* → api · /ws/* → realtime · else → Next.js        candidate. → Next.js candidate portal (isolated cookies)
  api. ws. eye. livekit.(→7880) storage.(→azurite) downloads.(installers + update manifest)
Docker Desktop (WSL2)
  core : postgres17+pgvector · valkey · azurite · clamav · mailpit
  app  : api · realtime · worker+beat · media-worker · interview-agent · vision-agent · coding-service · sandbox-runner(isolated net)
  media: livekit-server (7880 ws / 7881 tcp / 7882 udp-mux) · livekit-egress
  obs  : otel-lgtm (Grafana/Tempo/Loki/Prometheus) · glitchtip
  test : keycloak (SAML/OIDC test IdP) · webhook-receiver · ats-mocks
External APIs (HTTPS, keys in the gitignored root .env): Gemini (dev LLM, embeddings, vision) · OpenAI (production LLM, embeddings, vision, TTS fallback) · Deepgram (STT, TTS)
```

### 5.2 Docker Desktop stack

- **Compose file:** `infrastructure/local/compose.yaml`, with profiles `core`, `app`, `media`, `obs` and `test`.
- **Task runner commands:** `up`, `down`, `reset`, `seed`, `logs`, `doctor`.
- **Dockerfiles:** every backend service has a production Dockerfile: multi-stage, non-root, digest-pinned.
  - Locally, source code is bind-mounted with hot reload.
  - If file-watching on Windows mounts is too slow, the API can run natively with uv instead.
- **`doctor` script:**
  - Checks Docker resources, ports, hosts entries, Caddy CA trust, WebView2 and the MSVC build tools.
  - Verifies the Gemini, Deepgram and (when set) OpenAI keys with a harmless API call and lists the models your keys can use.
- **Seed data:**
  - A super admin, 2 organisations (for tenant-isolation checks) and users for every role.
  - Departments, teams, jobs, templates and a question library.
  - 200 synthetic resumes:
    - single- and multi-column layouts and tables
    - scanned PDFs and JPG/PNG images
    - Indian personal-details sections
    - hidden-text injection samples
    - an EICAR malware test file

### 5.3 AI stack (Gemini for development, OpenAI for production, Deepgram for speech)

Decided on 2026-09-28 (ADR-0002, ADR-0003): AI runs on hosted APIs through your keys, instead of local models, so no GPU is needed. Gemini (your paid key) is the LLM for development and testing; OpenAI is the production LLM; Deepgram handles speech in both.

- **One interface layer:** every AI call goes through `hirevion_core.ai`:
  - `LLMService`, `EmbeddingService`, `SpeechToTextService`, `TextToSpeechService`, `VisionService` (§78), plus `OCRService`.
  - Each call records model, prompt and rubric versions plus usage.
- **Profiles:** `dev` (Gemini + Deepgram) for development and testing, `production` (OpenAI + Deepgram), and `mock` (CI and load tests). The provider and model for each route are set in configuration.

| Capability | `dev` profile | `production` profile | Fallback | `mock` (CI and load tests) |
|---|---|---|---|---|
| LLM (JSON-schema output) | Gemini through its OpenAI-compatible endpoint: a fast model for live interview turns, the strongest model for screening and evaluation | OpenAI: same split | Azure OpenAI deployment of the production models (recommended) | Deterministic fake |
| Embeddings (1,536-d) | Gemini `gemini-embedding-001` with `output_dimensionality=1536` | OpenAI `text-embedding-3-large` with `dimensions=1536` | — | Deterministic fake vectors |
| STT | Deepgram streaming (Nova-3, or Flux for conversational end-of-turn) with keyterms from the JD and resume | same | OpenAI transcription | Scripted transcript |
| TTS | Deepgram Aura-2 streaming | same | OpenAI TTS; ElevenLabs/Cartesia optional later | Silent audio of realistic length |
| VAD / turn-taking | Silero VAD + LiveKit turn detector (+ Flux end-of-turn when used) | same | — | same |
| OCR | Tesseract 5, with Gemini vision for low-confidence pages | Tesseract 5 + OpenAI vision | — | Fixture text |
| Vision (proctoring) | MediaPipe on-device; OpenCV + ONNX Runtime + an Apache-2.0 detector server-side | same | — | Fixture detections |

- **Voice wiring:** LiveKit Agents' `deepgram` and `openai` plugins (the `openai` plugin points at Gemini's OpenAI-compatible endpoint in `dev`), with `FallbackAdapter` for STT, LLM and TTS.
- **Other LLM work:** the OpenAI Python SDK with JSON-schema structured outputs, against Gemini's OpenAI-compatible endpoint in `dev` and OpenAI in `production`, so one code path serves both. Pydantic validates every response, with one repair retry.
- **Embeddings across providers:** vectors from different providers aren't comparable, so each stored vector records its model, and switching providers runs the re-embed job.
- **Model choice:** model names live in configuration, never in code. The SP-00 benchmark lists the models your keys can use and picks the ones that keep the AI's first spoken word at p95 ≤ 2.5 s.
- **Keys:** only in the gitignored root `.env` locally (Key Vault in the cloud). Never in the repo, the desktop app or the web bundle.
- **Data rule:** development uses synthetic data. Real candidate data goes to an AI vendor only after its DPA is signed and its data-retention and model-improvement opt-outs are in place (§17). Gemini's paid tier doesn't use prompts to improve Google's products.
- **Cost control:** every call is metered (§11) against per-organisation budgets, so the cost model is built from real spend.

### 5.4 Cloud-portability contract (input to the Cloud Migration Plan)

- **Rules:**
  - 12-factor config via pydantic-settings.
  - Everything containerised.
  - No local-only logic in domain code.
  - Health and readiness probes; graceful shutdown.
  - Migrations run as a job.
- **Local service → cloud target:**
  - Azurite → Azure Blob (user-delegation SAS)
  - Valkey → Azure Managed Redis
  - Postgres → Azure Database for PostgreSQL Flexible Server with pgvector
  - Mailpit → Azure Communication Services Email (SMTP)
  - ClamAV → ClamAV + Defender for Storage
  - Self-hosted LiveKit → LiveKit Cloud or VMs/AKS
  - The `production` AI profile (OpenAI + Deepgram), plus an Azure OpenAI failover deployment (recommended) and a re-embed of stored vectors
  - Docker sandbox → Azure Container Apps dynamic sessions (Hyper-V) or Kata containers
  - Caddy → Front Door WAF
  - `.env` → Key Vault with managed identity
  - Grafana LGTM + GlitchTip → Azure Monitor / Application Insights
  - Static downloads server → Blob + Front Door
- **Sizing:** metering data and the cost model (§11) size the Azure SKUs.

## 6. Component designs

### 6.1 Backend

- **`api`:**
  - Conventions:
    - `/api/v1` prefix and OpenAPI 3.1.
    - RFC 9457 error responses.
    - Cursor pagination.
    - `Idempotency-Key` on create endpoints.
  - Each module is a router → service → repository chain with its own policies and domain events. It covers every §87 logical module plus a few additions:
    - auth, identity, organizations, rbac
    - jobs, documents, resumes, candidates, screening
    - templates, questions, interviews, candidate_access, third_eye
    - proctoring, recordings, coding, evaluations, reports, analytics
    - notifications, webhooks, integrations, public_api
    - audit, retention, usage, ai_governance, desktop_releases, platform (super admin)
- **`realtime`:**
  - The §91 channels `/ws/interviews/{id}`, `/ws/proctoring/{id}` and `/ws/recruiter/{id}`, plus a per-user notification channel.
  - Authorisation per channel.
  - Redis Streams consumer groups; clients resume from the last event ID.
  - Heartbeats and backpressure.
- **`worker` (Valkey-stream consumers, ADR-0015; replaces the planned Celery worker):**
  - Consumer groups per topic: `documents`, `ai_batch`, `ai_eval`, `reports`, `notify`, `webhooks`, `integrations`, `retention`, `metering`.
  - Fed by the transactional outbox; delivery at least once, with de-duplication by event id, retries and a dead-letter stream.
  - Runs inside the API (`HV_API_RUN_WORKERS`) or alone (`hv worker`).
  - Scheduled jobs (SP-18, SP-22) publish events from a small scheduler.
- **`media-worker`** runs ffmpeg (LGPL build) as a separate process. It verifies and assembles segments, makes thumbnails and cuts evidence clips.
- **`interview-agent`** runs the voice pipeline and the orchestrator (§6.8). **`vision-agent`** runs server-side vision (§6.12). Both are LiveKit Agents workers, dispatched explicitly per interview session.
- **`coding-service`** handles code runs and submissions. **`sandbox-runner`** is the only component with Docker-socket access and sits on an isolated network.
- **Shared `hirevion_core` library:**
  - Settings, database (SQLAlchemy 2 async + asyncpg, Alembic) and tenancy context.
  - Authorisation, outbox/events, storage and AI providers.
  - Audit, metering, clock sync and crypto.

### 6.2 Recruitment Platform (web) — screens (§7 IA)

- **`/dashboard`:**
  - The ten §10 KPIs: Open Jobs, Active Candidates, Screened, Shortlisted, Interviews Scheduled, Live, Completed, Pending Reviews, Proctoring Alerts, Hiring Pipeline.
  - All seven filters: Date, Recruiter, Team, Job, Department, Candidate status, Interview status.
  - A hiring-pipeline board (kanban by the §72 statuses).
- **`/jobs`:**
  - Tabs: All, Draft, Open, Paused, Closed, Archived.
  - Create and edit (17 fields).
  - JD input and review/edit of the extracted requirements.
  - Screening configuration (inherits the organisation default).
  - Resume upload (single, bulk, ZIP) with a processing monitor.
  - Ranking with an evidence drawer, and bulk actions.
- **`/candidates`:**
  - Tabs: All, Screening, Shortlisted, Interview, Completed, Final Decision.
  - **Candidate 360** with all 13 §20 tabs: Profile, Resume, Applications, Screening, Interview History, Technical Skills, Coding, AI Interview, Proctoring, Recordings, Reports, Recruiter Notes, Activity Timeline.
- **`/interviews`:**
  - Tabs: Upcoming, Live, Completed (including the **pending-review queue**), Templates.
  - Assign (single or bulk), with reviewers assigned.
  - Live monitor.
  - Review workspace.
- **`/questions`:**
  - Categories: Technical, Coding, System Design, Resume-Based, Custom.
  - An AI generator with review and approval before questions become reusable.
- **`/reports`:** Interview, Proctoring, Candidate (the internal report) and Analytics.
- **`/admin`:**
  - Users, Roles, Teams, Departments.
  - AI, Integrations, Security, Proctoring Policies.
  - Retention & DSR, Branding, Webhooks, API Keys.
  - Usage & Cost, Audit Logs.
  - Organisation profile and defaults.
- **`/platform`** (Super Admin):
  - Organisations.
  - Global AI and security settings.
  - The app category catalogue.
  - Desktop releases.
  - Platform audit and health.
- **Notification centre** (in-app bell) and **same-origin routing:** `/api` and `/ws` are served on the app host, with a host-only `__Host-` session cookie and no CORS.
- **UX:**
  - The design system comes first.
  - Every table filters, sorts and paginates on the server, with saved views.
  - Bulk actions and keyboard navigation.
  - WCAG 2.2 AA; every chart has a data-table equivalent.

### 6.3 Candidate portal (separate host, isolated cookies)

- Accept the invitation, set a password, verify email.
- Download the app, with system requirements and install help.
- Privacy, recording, proctoring and retention notices, the deletion process and the support contact (§83).
- Interview status and window.
- Candidate-visible report (§99).
- Requests:
  - reschedule
  - support
  - accommodation or alternative process
  - data rights (access, correction, erasure, grievance, nomination)
  - consent withdrawal

### 6.4 AI Interview Desktop (Tauri 2)

- **Flow** (a superset of §26). Each step, in order:
  1. Launch.
  2. **Version check / update gate:** signed updater; the minimum version comes from the desktop release registry.
  3. **Login** with email and password. The backend verifies the six §28 items: account, assigned interview, job, status, expiry, app version.
  4. An email OTP on a new device (org-configurable), which also registers the device key.
  5. Choose the interview, with window countdown and expired states.
  6. **System check** (all 11 §29 items; which are mandatory is set by policy):
     - camera, mic level, speaker test, screen-capture test
     - network bandwidth and the LiveKit `ConnectionCheck`
     - CPU, memory, disk, display count
     - Windows camera/mic privacy toggles, with `ms-settings:` deep links
     - third-eye readiness
     - plus Media Foundation H.264 support and the WebView2 version
     - results are stored for the §68 "Device Checks" section.
  7. **Instructions:** the six §30 items, configured per template or organisation.
  8. **Itemised consent** (all 10 §30 items), recorded per purpose, with an accommodation request.
  9. **Third-eye setup:** QR pairing, live preview and placement guide.
  10. **Environment check:** blocked apps, overlays, remote-session and VM checks, the display rule.
  11. **Ready**, with a practice question.
  12. **Interview** in fullscreen, using the §32 layout: timer, AI voice orb, captions/transcript, workspace panel, and a status bar showing Camera, Mic, Screen, Third Eye and Secure Session.
  13. **Completion:** the upload drains with progress; the app says it's "safe to close" only after every segment is acknowledged, then asks for feedback.
  14. Exit.
- **Workspace per question type:**
  - Coding: Monaco with a language dropdown, Run, Submit and test results.
  - System design: whiteboard.
  - Everything else: question card and notes.
- **Rust crates** in `src-tauri/crates/` (a superset of §93):
  - `security` — CNG/TPM device key, DPoP signer, DPAPI token vault, environment sanitisation, debugger and self-signature checks, single instance.
  - `api-client` — reqwest with rustls, DPoP, retries.
  - `screen-capture` — Windows Graphics Capture with a DXGI fallback; every display; preview frames; on-demand snapshots.
  - `recorder` — Media Foundation H.264 segmenter.
  - `segment-store` — AES-256-GCM files with a SQLite manifest.
  - `uploader` — resumable, bandwidth-aware, waits for server acknowledgement.
  - `event-queue` — signed, sequenced, acknowledged, offline-safe.
  - Monitors: `process-monitor`, `window-monitor`, `display-monitor`, `device-monitor`.
  - `lockdown` — driven by policy; can optionally suppress shortcuts but never records keys.
  - `system-check`.
- **Webview modules** (§93 `src/`):
  - `auth`.
  - `interview` — the §33 orb states, captions and candidate controls.
  - `coding` — Monaco, the whiteboard and telemetry.
  - `proctoring` — a MediaPipe worker.
  - `third-eye`.
  - `recording` — WebCodecs with the Mediabunny muxer, handing segments to Rust.
  - `services` — the LiveKit room (publishes mic, camera and a screen-preview track built from Rust frames), the WebSocket control channel, and API calls routed through Rust.
  - `i18n` and `a11y`.
- **Hardening:**
  - Minimal Tauri capabilities.
  - A strict CSP: `connect-src` allows only the API, WebSocket, LiveKit and storage hosts; `'wasm-unsafe-eval'` is allowed only for MediaPipe.
  - No devtools in release builds and no remote content.
  - The refresh token never reaches the webview.
  - **No DB, Redis, storage, LiveKit or LLM master credentials** in the app (§8).
- **Accessibility (§101):**
  - High-contrast / forced-colours support.
  - Captions and the full transcript on screen.
  - Clear permission instructions.
- **Accommodations**, approved by a recruiter:
  - Extended time.
  - Text-answer mode.
  - Breaks.
  - A screen reader or magnifier on the process allowlist.
  - Relaxed gaze/face-distance rules.
  - Third-eye waiver.

  Reviewers can see which accommodations applied.

### 6.5 Third-eye (mobile browser, separate Vite app — §52, §92)

1. The desktop requests a pairing token, which is short-lived, single-use, and bound to the interview and the candidate (the five §52 properties). It shows a QR code.
2. The phone opens the `eye.` page and redeems the token.
3. The phone receives a LiveKit token that can only publish a camera feed.
4. It walks the candidate through camera permission on iOS Safari and Android Chrome.
5. A placement guide shows where to put the phone.
6. The phone streams its rear camera at 720p, 15 fps. Wake Lock, visibility handling and auto-reconnect keep the stream alive.
7. Status events go to the desktop and the recruiter: connected, disconnected, reconnected.

Pairing again revokes the old device. Egress records the stream.

### 6.6 Document pipelines (§12–14)

- **JD pipeline** (§12): accepts PDF, DOCX, TXT or pasted text.
  1. Validate.
  2. Scan.
  3. Extract text.
  4. Normalise.
  5. Detect sections.
  6. Extract skills.
  7. Extract requirements.
  8. Extract experience.
  9. Embed.
  10. Build the screening profile.

  It extracts role/title, required and preferred skills, experience, responsibilities, qualifications, domain requirements, and location/work model. **The recruiter reviews and edits** before the profile is used, and every edit is versioned in `job_versions`.
- **Resume pipeline** (§13–14): accepts single files, bulk uploads or ZIP; PDF, DOCX, TXT, or JPG/PNG/TIFF.
  1. Upload.
  2. Validate: magic bytes, size, page count, ZIP limits.
  3. ClamAV scan, with quarantine.
  4. Extract text with pdfplumber/pypdfium2, python-docx (safe XML) or charset-detected TXT.
  5. OCR if needed.
  6. Normalise and detect sections.
  7. Scan for hidden text and injection attempts.
  8. Detect and mask PII with built-in recognisers (ADR-0015): Aadhaar (Verhoeff checksum), PAN, phone, email and date of birth; Aadhaar and PAN are masked before storage or any AI call.
  9. LLM structured parse of the 16 §14 fields, each with evidence (page, section, quote).
  10. Verify every quote against the source text.
  11. Build the candidate profile and de-duplicate by email, phone, fuzzy name or file hash.
  12. Normalise skills to the taxonomy.
  13. Create embeddings.
  14. Screen.

  Each document has a status and can be retried.

### 6.7 Screening & ranking (§15–18)

- **Inputs:** JD, structured job profile, resume, screening configuration (§15).
- **Evaluation factors** (the nine §15 factors):
  - required and preferred skills
  - experience
  - relevant roles and projects
  - technology match
  - domain
  - education, when configured
  - location/work model, when configured
- **Methods:** structured rules, semantic matching, skill matching, experience matching (overlap-aware), embeddings, and LLM reasoning.
- **Knock-out rules** only flag; they never auto-reject.
- **Output** (the nine §16 fields): candidate, rank, match score, skill match, experience match, relevant evidence, missing requirements, strengths, concerns. Every major factor carries verified evidence.
- **Weights** are configured per §17, with required/preferred/optional skill classes; the organisation default is inherited.
- **Workflow statuses** (§18): Uploaded → Parsed → Screened → Ranked → Recruiter Review → Shortlisted.
- **Recruiter actions:**
  - Shortlist, reject, hold, review.
  - Assign a recruiter or hiring manager.
  - Create an interview.
  - Export to CSV/XLSX.
  - All of these work in bulk.
  - Manual overrides are audited.
- **Reproducibility:** results are cached by (resume hash, JD version, config version, model/prompt version).
- **Rate budgets:** live-interview AI traffic has a reserved rate budget; bulk screening runs in per-organisation fair queues.
- **Blind mode** is on by default.

### 6.8 AI interview engine (§33–43)

- **The nine §34 components** (in the order they act):
  1. `ContextBuilder` — collects resume evidence, the JD profile, the template version and the question library.
  2. `SkillMatrixBuilder` — sets weights, coverage targets, a difficulty ladder and resume hooks for each skill.
  3. `QuestionPlanner` — builds an ordered plan with time budgets, using library questions or generated ones; each question's source is stored (§36).
  4. `AnswerAnalyzer` — rates correctness, completeness, depth, missing concepts and contradictions (§38).
  5. `DifficultyController` (§39).
  6. `FollowUpGenerator`:
     - strong answer → go deeper
     - partial answer → targeted follow-up
     - weak answer → clarification
     - repeated weak answers → move to another skill
  7. `CodingController` (SP-16).
  8. `TimeController` — tracks start, deadline, remaining time, question duration and coding duration, and shrinks the plan without dropping required skills (§40).
  9. `CompletionEvaluator`.
- **State** (all 12 §34 fields): candidate, job, resume, skills, questions asked, topics covered, difficulty, answer quality, remaining time, current topic, coding state and a **proctor-event summary**. Policy can have the AI remind the candidate after CRITICAL events, e.g. "your camera appears covered".
- **States** (all ten §35 states, recorded with timestamps):
  1. START
  2. INTRODUCTION
  3. EASY → MEDIUM → HARD — the per-skill ladder, following the template's difficulty distribution
  4. ADAPTIVE FOLLOW-UP — a sub-state entered from any rung
  5. CODING (if configured)
  6. FINAL QUESTIONS — answered only from the organisation's FAQ
  7. COMPLETION
  8. EVALUATION

  Per-question time limits and follow-up rules (§22) are honoured. Coverage of required JD skills is tracked live (§37).
- **Division of labour:** a deterministic Python policy makes the decisions; LLMs only analyse answers and phrase questions. This avoids "one giant prompt" (§34).
- **Latency:** target is p95 ≤ 2.5 s until the AI starts speaking.
  - Path: end of turn → final transcript → answer analysis, while a short acknowledgement plays → policy → streamed question → streamed TTS.
  - Likely next questions are generated while the candidate speaks.
- **Voice:**
  - The six §33 states.
  - Streaming STT/TTS (§42): interruption handling, audio-state tracking, failure fallbacks.
  - STT is primed with keyterms from the JD and resume skills.
  - TTS uses a pronunciation lexicon for tech terms.
- **Transcript:**
  - Each segment stores speaker, text, start, end, question_id and confidence (§41). Both sides are stored (§43).
  - Transcript artifacts (JSON/VTT/TXT) are saved to storage (§85).
- **Guardrails:**
  - The AI never reveals scores or answers.
  - It handles "repeat", "I don't know", silence nudges and off-topic answers.
  - Manipulation attempts are flagged.
- **Continuity:**
  - Hot state in Redis, with a Postgres checkpoint every turn.
  - After an agent crash, the agent is re-dispatched and resumes from the checkpoint.
  - If the candidate disconnects, the interview pauses under the resume policy and restarts with a recap.

### 6.9 Evaluation & AI governance (§44, §70, §79)

- **Two evaluators:**
  - A live, fast `AnswerAnalyzer` steers the conversation.
  - An async `QuestionEvaluator` scores the eight §44 dimensions: relevance, correctness, completeness, technical depth, reasoning, clarity, communication, evidence. Every score cites timestamped transcript quotes.
- **Aggregation:** skill and final evaluations (§70) are rubric-weighted, with evidence. Strengths, knowledge gaps and follow-up performance are synthesised from them.
- **`ai_invocations`** stores the eight §79 fields:
  - model name and version
  - prompt, rubric and evaluation versions
  - timestamp
  - input references
  - output

  It also stores tokens, latency and cost.
- **Change control:**
  - Prompts and rubrics are versioned files.
  - Re-running an evaluation with pinned versions reproduces its results.
  - A change activates only after passing the eval harness: extraction F1, ranking agreement, score correlation with human raters, latency.

### 6.10 Coding (§45–48)

- **Flow:** the AI asks a coding question → Monaco → Run → Tests → Submit → Evaluation.
- **Questions** carry starter code per language, plus visible, hidden, edge-case and performance tests.
- **Sandbox path:** `coding-service` → queue → `sandbox-runner` → a fresh container for each run, destroyed afterwards. Container limits:
  - No network.
  - Read-only root filesystem, with a size-capped tmpfs.
  - CPU, memory, process-count and time limits.
  - `cap-drop ALL`, `no-new-privileges`, seccomp, non-root user.
- **Runners:**
  - Python
  - Node (JavaScript)
  - TypeScript (tsx)
  - SQL, against a throwaway PostgreSQL or SQLite
- **Evaluation** (the eight §47 criteria): correctness, test cases, edge cases, time and space complexity (measured plus LLM analysis), code quality, readability, approach.
- **Stored:** final code, every submission, test results, execution time and memory.
- **Telemetry** (the eight §48 events): typing start/stop, code changed, run, submit, copy, paste, cut, editor focus change. No global keystroke capture.
- **Coding report:** its own view and export.

### 6.11 Recording pipeline (§49–51, §95)

- **Local capture:**
  - Screen: every display, captured natively → 10-second H.264 MP4 segments.
  - Camera and mic: 10-second WebCodecs segments, falling back to MediaRecorder.
  - Every segment is AES-256-GCM encrypted.
- **Upload:**
  - Write-only SAS URL per blob.
  - Exponential backoff.
  - Throttled to give way to live media.
- **Acknowledgement:** the server acknowledges each segment after checking its hash. The desktop deletes a local segment only after that acknowledgement (§51).
- **Recovery:** after a crash or network loss, pending segments upload on the next launch.
- **Server-side copies:**
  - Conversation audio: Egress of the candidate's mic plus the agent's own TTS, mixed together — an independent copy.
  - Third-eye: Egress recording.
  - Locally, both pass through a shared volume.
- **Evidence snapshots:** on-demand screen and camera snapshots at event time.
- **Assembly:** `media-worker` builds one file per track plus a timeline map. Missing segments raise `SCREEN_CAPTURE_STOPPED` or `TELEMETRY_GAP`.
- **Storage layout** follows §85: `/{org}/jobs/`, `/{org}/candidates/`, `/{org}/interviews/{id}/{screen,camera,audio,third-eye,evidence,transcript,report}/`.

### 6.12 Proctoring engine & computer vision (§53–67)

- **Pipeline** (§54):
  1. The seven sources: candidate camera, third eye, screen, native agent, coding editor, audio, interview state.
  2. Normaliser.
  3. Temporal aggregator.
  4. Rule engine.
  5. Evidence manager.
  6. Severity.
  7. Realtime alert.
  8. Report.
- **Event schema** (§67): `event, timestamp, duration_ms, confidence, evidence[]`, plus source, severity, session sequence and policy version.
- **Default severities** (org-configurable, per §64):

| Event | Source | Default |
|---|---|---|
| FACE_ABSENT | camera | WARNING > 5 s, CRITICAL > 30 s |
| MULTIPLE_FACES / UNEXPECTED_PERSON_DETECTED | camera / third-eye | CRITICAL > 3 s |
| PHONE_DETECTED | camera / third-eye | CRITICAL |
| GAZE_DEVIATION | camera | INFO; WARNING if sustained > 10 s; never CRITICAL alone |
| CAMERA_OBSTRUCTED | camera | CRITICAL > 5 s |
| CAMERA_DISCONNECTED / MIC_DISCONNECTED | device + server-observed | CRITICAL > 10 s |
| SCREEN_CAPTURE_STOPPED | native + upload continuity | CRITICAL after configured duration |
| APPLICATION_FOCUS_CHANGE / WINDOW_MINIMIZED | native | WARNING > 3 s |
| BLOCKED_PROCESS_DETECTED | native | CRITICAL for blocked categories, else WARNING |
| EXTERNAL_DISPLAY_CHANGE | native | WARNING (CRITICAL under a single-display policy) |
| THIRD_EYE_DISCONNECTED | server-observed | WARNING > 10 s, CRITICAL > 60 s when required |
| CAPTURE_EXCLUDED_WINDOW / REMOTE_SESSION_DETECTED / CLIENT_INTEGRITY_WARNING | native | CRITICAL |
| VIRTUAL_DEVICE_DETECTED / ADDITIONAL_SPEAKER_DETECTED / TELEMETRY_GAP | native / audio / server | WARNING |
| VM_DETECTED, *_RECONNECTED, SESSION_INTERRUPTED/RESUMED | native / server | INFO |

- **On-device, MediaPipe, 5–10 fps:**
  - Face: the five §56 signals (present, absent, multiple, too far, too close), with temporal thresholds.
  - Gaze (§57): landmarks → eyes → gaze → smoothing → extended left, right or down.
  - Pose and hands (§58): hands below frame, repeated downward movement, typing posture, unusual hand movement — correlated with editor telemetry.
  - Phone and objects.
  - Camera obstruction.
- **Server `vision-agent`** (OpenCV preprocessing and optical flow, plus ONNX Runtime with an Apache-2.0 detector and MediaPipe Pose/Hands, at 1–2 fps):
  - Third-eye (§53): posture, hands, phone, additional person, secondary screen, workspace, unusual movement.
  - Verifies on-device CRITICAL events; a disagreement raises `CLIENT_INTEGRITY_WARNING`.
  - Correlates the two cameras.
- **Audio** (§59):
  - Speech rate, pauses, response latency, filler words, prosody (descriptive only), repetition.
  - Detection of additional speakers.
  - None of these is ever presented as proof of cheating.
- **Native Windows monitoring** (§60–63):
  - Process metadata: name, PID, path, publisher/signature, start time, window info.
  - Policy (§61): blocked applications, blocked categories and allowed applications, matched by name, path, publisher, signature, hash or window title — never by name alone.
  - Focus (§62): losing focus, foreground change, minimise, unexpected window; stores timestamp, previous app, new app and duration.
  - Display and device changes (§63).
- **Recruiter review of events:** each event can be confirmed or dismissed as a false positive, with a reason, and is audited. This feeds the §106 false-positive KPI.
- **Candidate nudges** are configurable.
- **Live dashboard** (§65–66):
  - Candidate, camera, screen, third-eye, AI status, transcript, recent events, connection health.
  - Viewed with a hidden, subscribe-only token.
  - Opening it is audited.

### 6.13 Reports, review & Candidate 360 (§19–20, §68–72, §98–99)

- **Reports:**
  - **Interview report** — all 13 §69 sections: executive summary, metadata, questions, answers, skill evaluation, technical evaluation, coding evaluation, communication, strengths, knowledge gaps, follow-up performance, transcript, timeline.
  - **Proctoring report** — all 14 §68 sections: session summary, device checks, camera/mic/screen/third-eye status, application events, process events, face events, gaze events, object events, timeline, evidence, reviewer notes.
  - **Coding report**.
  - **Internal candidate report**.
  - **Candidate-visible report** (§99): completion, general feedback, technical feedback, coding feedback, next-step status. The organisation chooses which items to show, and a recruiter approves each release.
  - Every report is available as a web view and as a PDF (rendered by Playwright). PDFs are stored in `report_exports`, and viewing or downloading a report is audited.
- **Review workspace** (all 11 §71 actions):
  - Transcript and recordings in a synchronised player (camera, screen, third-eye, audio) on one timeline.
  - Jump to evidence.
  - Code and test results.
  - Screening result, evaluation, proctoring events.
  - Notes, export, workflow status.
- **Recruiter and hiring-manager actions:**
  - **Hiring Manager input:** a structured recommendation with a rationale.
  - Score changes with a reason, audited.
  - Hiring workflow statuses — all nine §72 statuses, every change audited.
  - The final decision, made only by an authorised human.
- **Candidate 360:** the §19 profile, all 13 §20 tabs, and a unified timeline across the eight §98 sources.

### 6.14 Notifications & webhooks (§75, §77)

- **Notification channels:** email, in-app and webhook.
- **Notification events** (all 8 in §75): invitation, reminder, reschedule, interview completed, report ready, candidate shortlisted, candidate status changed, proctoring alert.
- **Localised templates** and per-user preferences.
- **Webhook events** (all 9 in §77): `candidate.created`, `candidate.shortlisted`, `interview.created`, `interview.started`, `interview.completed`, `evaluation.completed`, `report.ready`, `candidate.selected`, `candidate.rejected`.
- **Webhook delivery:**
  - HMAC-SHA256 signature, timestamp and replay protection.
  - Exponential retries.
  - Delivery logs and redelivery.
  - Secret rotation.
  - Delivery through an SSRF-safe outbound client.

### 6.15 Enterprise identity (§8, Phase 10)

- **Per-organisation SSO:** Entra ID (OIDC), generic OIDC and SAML 2.0.
- **Home-realm discovery** by verified email domain.
- **Just-in-time provisioning** with role mapping.
- **SCIM 2.0**, passkeys (WebAuthn), and an SSO-only mode.
- **TOTP MFA with recovery codes** (moved from SP-02), enforceable per organisation.
- **Tested** against Keycloak locally and an Entra test tenant.

### 6.16 ATS integrations & public API (§76)

- **One provider-neutral adapter interface** covering jobs, candidates, applications, status and results.
  - The sync is idempotent, with an external-ID mapping.
  - No provider-specific logic lives in the core services; a lint rule enforces this.
- **Adapters:**
  - Custom REST (outbound, with field mapping)
  - Webhooks
  - Greenhouse
  - Lever
  - Workday
  - SAP SuccessFactors
  - Oracle Recruiting
  - iCIMS

  Each is built against the vendor's documented API, with contract tests against local mocks. Live certification needs each vendor's sandbox credentials.
- **Public REST API** with scoped, hashed organisation API keys, rate limits and published docs.

### 6.17 Analytics & KPIs (§10, §73–74, §106)

- **All 12 §73 analytics:**
  - applications per job
  - screening conversion
  - shortlist rate
  - interview completion
  - interview duration
  - average skill scores
  - coding performance
  - proctoring events
  - recruiter activity
  - time to shortlist
  - time to interview
  - candidate funnel
- **The full nine-stage funnel** (§74).
- **All 20 §106 KPIs.** Definitions of the less obvious ones:
  - **Screening quality** — agreement between the AI rank and recruiter decisions, the override rate, and interview outcomes of shortlisted candidates.
  - **Recruiter time saved** — resumes auto-screened × a configurable baseline in minutes.
  - **Candidate drop-off** — measured per desktop onboarding step.
  - **False-positive rate** — from the event review outcomes.
- **Bias/adverse-impact view**, accessible charts with table equivalents, and CSV export.

### 6.18 Administration & governance (§6, §9, §61, §64, §83–84, §102)

- **Organisation settings:**
  - Profile.
  - Branding: web, emails, portal, desktop, third-eye.
  - Default screening configuration.
  - Default interview configuration.
- **AI configuration:** profile, model and prompt version per route, plus thresholds. Every change is audited.
- **Proctoring policy editor:**
  - Presets: Off, Basic, Standard, Strict.
  - Per-event thresholds and severities.
  - Blocked and allowed apps and categories.
  - Accommodation rules.
- **Retention** (§84 classes): a retention engine and legal holds. DSR workflows, consent records and versioned policy documents.
- **Usage, cost and quotas.**
- **Super Admin:**
  - Organisations (create, suspend, quotas).
  - Global AI and security settings.
  - The platform-maintained app category catalogue: remote access, screen sharing/meetings, AI assistants/overlays, messaging, screen recorders, VMs/emulators, and optionally browsers and dev tools.
  - Desktop releases (channel, minimum version, rollout percentage).
  - Platform audit and health.
- **Localisation packs** (§102): UI strings, email templates, interview instructions and policy text. en-IN and en-US come first.

## 7. Data model & tenancy (§81, §85, §89)

- **Every §89 table**, implemented by its owning sub-project:
  - Organisations and access: `organizations`, `organization_settings`, `users`, `roles`, `permissions` (the catalogue lives in code; custom roles' grants are `role_permissions`, ADR-0014), `user_roles`, `teams`.
  - Jobs: `jobs`, `job_versions`, `job_skills`.
  - Candidates and resumes: `candidates`, `candidate_documents`, `applications`, `resume_parses`, `resume_skills`, `resume_embeddings`, `screening_results`.
  - Interview configuration: `interview_templates`, `interview_template_versions`, `question_library`, `question_versions`.
  - Interviews: `interviews`, `interview_sessions`, `interview_questions`, `interview_answers`, `transcripts`, `transcript_segments`.
  - Coding: `coding_sessions`, `coding_questions`, `coding_submissions`, `coding_test_results`.
  - Proctoring and recording: `proctor_sessions`, `proctor_events`, `proctor_evidence`, `proctor_metrics`, `third_eye_sessions`, `recordings`, `recording_segments`.
  - Evaluation and reports: `skill_evaluations`, `question_evaluations`, `interview_evaluations`, `reports`, `report_exports`.
  - Platform: `notifications`, `webhooks`, `integrations`, `audit_logs`.
- **Added tables:**
  - Organisation structure: `departments`, `team_members`, `role_permissions`.
  - Recruiter identity: `web_sessions`, `auth_tokens` (single-use set-password, reset and email-confirmation links, ADR-0013), `mfa_factors`, `recovery_codes`, `sso_connections`, `verified_domains`, `scim_tokens`. An invitation is an `invited` user plus a set-password link (ADR-0014), so there is no separate invitations table.
  - Candidate identity: `candidate_accounts`, `candidate_devices`, `candidate_otps`.
  - Jobs and applications: `job_documents`, `candidate_notes`, `application_status_history`, `hiring_inputs`.
  - Interview lifecycle: `interview_reviewers`, `invitations`, `consents`, `policy_documents`, `accommodations`, `system_check_results`, `session_interruptions`.
  - Screening: `skills_taxonomy`, `skill_aliases`, `screening_configs`.
  - AI governance: `prompt_versions`, `rubric_versions`, `ai_invocations`.
  - Metering: `usage_events`, `quotas`.
  - Events and delivery: `outbox_events`, `webhook_deliveries`, `notification_preferences`, `api_keys`, `external_id_mappings`.
  - Proctoring policy: `proctor_policies`, `app_rules`, `app_categories`, `proctor_event_reviews`.
  - Retention and data rights: `retention_policies`, `legal_holds`, `dsr_requests`.
  - Platform: `desktop_releases`, `feature_flags`.
  - Fairness: `self_id_responses` (restricted access).
- **Conventions:**
  - UUIDv7 keys and UTC `timestamptz`.
  - `organization_id` on every tenant row, with composite `(organization_id, id)` foreign keys.
  - Row-level security bound to `SET LOCAL app.org_id`.
  - Monthly partitions for `proctor_events`, `transcript_segments`, `audit_logs` and `usage_events`.
  - The audit log is append-only, with a hash chain per organisation.
- **State machines**, each with explicit transitions and tests:

| Entity | States |
|---|---|
| Job (§11) | Draft → Open ⇄ Paused → Closed → Archived |
| Screening stage (§18) | Uploaded → Parsed → Screened → Ranked → Recruiter Review → Shortlisted (or Rejected / On Hold) |
| Hiring workflow (§72) | the nine statuses, application-level, every change audited |
| Interview (§24) | Scheduled → Invited → In Progress ⇄ Interrupted → Completed → Evaluating → Evaluated; or Expired / Cancelled / Abandoned |
| Document | Uploaded → Scanning → (Quarantined) → Extracting → OCR → Parsing → Parsed / Failed |
| Recording segment | Captured → Encrypted → Queued → Uploading → Uploaded → Acknowledged → Purged locally |
| Proctor event | Detected → Aggregated → Raised → Reviewed (Confirmed / False positive / Not relevant) |
| Third-eye session | Issued → Redeemed → Connected ⇄ Disconnected → Revoked / Ended |
| Webhook delivery | Pending → Delivered, or Retrying → Failed (dead-letter) |
| DSR | Received → Verified → In Progress → Completed / Rejected |

## 8. API surface (§90) & realtime event catalogue (§91)

- **Resource groups** under `/api/v1` — all 20 from §90 plus additions:
  - `/auth`, `/organizations`, `/users`, `/jobs`, `/resumes`, `/candidates`, `/screening`
  - `/interviews`, `/interview-templates`, `/questions`, `/coding`, `/proctoring`, `/third-eye`, `/recordings`
  - `/evaluations`, `/reports`, `/analytics`, `/notifications`, `/integrations`, `/audit`
  - Added: `/candidate-auth`, `/candidate-portal`, `/desktop`, `/webhooks`, `/api-keys`, `/retention`, `/dsr`, `/usage`, `/platform`, `/scim/v2`.
- **PRD example endpoints**, implemented exactly as written:
  - `POST /jobs`, `POST /jobs/{id}/jd`, `POST /jobs/{id}/resumes`, `POST /jobs/{id}/screen`, `GET /jobs/{id}/screening-results`.
  - `POST /candidates/{id}/shortlist`, `POST /candidates/{id}/reject` — scoped to an application via `job_id`.
  - `POST /interviews`, `GET /interviews/{id}`, `POST /interviews/{id}/start` (verifies checks, consents and third-eye, then dispatches the agent).
  - `POST /interviews/{id}/answer` — text-answer mode.
  - `POST /interviews/{id}/complete`, `GET /interviews/{id}/transcript`, `GET /interviews/{id}/report`.
  - `POST /proctoring/session`, `POST /proctoring/events` (batched, signed, sequenced), `POST /proctoring/heartbeat`, `GET /proctoring/{interview_id}`, `GET /proctoring/{interview_id}/evidence`.
- **Key added endpoints:**
  - Candidate auth: login, OTP verify, device register, refresh, logout.
  - Desktop release check and update manifest.
  - Third-eye: issue, redeem, revoke, status.
  - Recordings: segment upload URL, segment acknowledgement, playback URLs.
  - Coding: run, submit, results, telemetry.
  - Clock sync.
- **Realtime events:** all ten from §91 plus additions.
  - §91: `AI_SPEAKING`, `CANDIDATE_SPEAKING`, `QUESTION_STARTED`, `ANSWER_RECEIVED`, `PROCTOR_EVENT`, `CODE_RUN`, `CODE_SUBMITTED`, `RECORDING_STATUS`, `THIRD_EYE_STATUS`, `INTERVIEW_COMPLETED`.
  - Added: `INTERVIEW_STATE_CHANGED`, `TRANSCRIPT_SEGMENT`, `ALERT`, `CONNECTION_HEALTH`, `HEARTBEAT`, `INTERVIEW_INTERRUPTED`, `INTERVIEW_RESUMED`, `NOTIFICATION`.
  - Schemas are shared as zod (TypeScript) and Pydantic (Python) models generated from one source.

## 9. Security architecture (target: OWASP ASVS 5.0 Level 2; covers every §82 item)

- **Web sessions:**
  - Opaque 256-bit IDs stored server-side.
  - `__Host-` cookie: Secure, HttpOnly, SameSite=Lax.
  - Session ID rotated at login and MFA.
  - Timeouts: 30 minutes idle, 12 hours absolute.
  - CSRF token plus Origin check.
  - Step-up re-authentication for exports and role changes.
- **Passwords:**
  - argon2id hashing.
  - Minimum 12 characters (15 where MFA isn't enforced), per NIST SP 800-63B-4.
  - Breached-password check.
  - Progressive lockout.
  - Rate limits per IP, account and organisation.
- **MFA:** TOTP with encrypted secrets, recovery codes and passkeys. Organisations can enforce it.
- **Candidate tokens:**
  - Access JWT: ES256, 10 minutes, carrying the device-key thumbprint (`cnf.jkt`).
  - Rotating refresh token: 8 hours absolute, with reuse detection.
  - Interview-session token scoped to the interview, session and device, expiring with the interview window.
  - A DPoP proof on every request, with a replay cache.
- **LiveKit tokens:** least privilege for each participant, short-lived. The third-eye token is single-use and revocable.
- **Storage URLs:**
  - Uploads: write-only SAS, per blob, 15 minutes.
  - Playback: read-only SAS, per blob, 5 minutes, audited.
- **Authorisation:**
  - RBAC matrix: 5 predefined roles plus custom roles per organisation.
  - Resource scope: users only reach the jobs, candidates and interviews assigned to them.
  - Row-level security.
  - Authorisation is always checked server-side (§81).
  - Super-admin access across tenants is audited.
- **Audit:** every one of the 16 §97 actions is recorded, append-only and hash-chained.
- **Files:**
  - Type sniffing.
  - Size and page limits.
  - Zip-bomb and decompression-bomb guards.
  - Safe XML parsing.
  - Parsers run in resource-limited workers.
- **Outbound requests:** an SSRF-safe client blocks private and link-local ranges and pins the resolved IP.
- **Encryption:**
  - TLS everywhere.
  - The desktop buffer uses AES-GCM.
  - TOTP secrets and integration credentials are envelope-encrypted.
  - Server-side encryption at rest (and optional customer-managed keys) arrives with the cloud plan.
- **Secrets:** never in the repo; `.env.local` for dev; Key Vault in the cloud.
- **LLM safety:**
  - Untrusted text is always passed as data.
  - Structured outputs only.
  - Evaluators have no tools.
  - Injection attempts raise flags.
- **Desktop:**
  - The §6.4 hardening.
  - Authenticode signing, Ed25519-signed updates and downgrade protection.
  - Integrity checks report `CLIENT_INTEGRITY_WARNING`.
- **Supply chain:**
  - Lockfiles and image digests.
  - SBOM (Syft).
  - Vulnerability scanning (osv-scanner, Trivy).
  - Secret scanning (gitleaks).
  - License checks (cargo-deny, pip-licenses, license-checker).
  - A STRIDE threat model per SP in `docs/security/`.

## 10. Privacy (DPDP) & responsible AI

- **Consent and notices:**
  - A consent service covering the ten §83 disclosures, per purpose, versioned against a notice hash, with withdrawal.
  - Candidates confirm they are at least 18.
  - Candidates are told AI is used.
- **Policy drafts** in `docs/policies/`, for counsel review: privacy, recording, proctoring, data retention, deletion process, support contact. These are drafts, not legal advice.
- **Data-subject-request workflows:**
  - Access export.
  - Correction.
  - Erasure, respecting legal holds.
  - Grievance.
  - Nomination.
- **Operations:**
  - A breach runbook.
  - A retention engine with the §84 defaults: screen/camera/third-eye recordings and raw events 90 days, reports 1 year, audit logs 1 year+. All are configurable per organisation.
- **Fairness:**
  - Blind screening on by default.
  - Adverse-impact monitoring.
  - No emotion inference.
  - A human decision is required to reject or select.

## 11. Observability, metering & cost model

- **Telemetry:**
  - OpenTelemetry across every service, agent, the desktop and the web app. Trace context propagates through outbox events, WebSockets and LiveKit metadata.
  - Log filters redact PII.
- **Dashboards and alerts** for all 14 §96 signals:
  - API, AI, STT and TTS latency
  - WebRTC health
  - recording health and upload failures
  - interview completion
  - worker queues
  - database, Redis and storage
  - desktop crash rate
  - proctoring engine health
- **GlitchTip** catches errors and crashes.
- **Metering, recorded at the source:**
  - LLM tokens by model.
  - STT seconds and TTS characters.
  - Media participant and egress minutes.
  - Storage bytes by data class.
  - Sandbox seconds and OCR pages.
  - Emails sent.
  - Service CPU-seconds.
- **Cost model (`tools/cost-model`):**
  - Multiplies vendor and Azure price tables (YAML) by measured usage per interview.
  - Outputs cost per interview plus monthly fixed cost at 10, 100 and 1,000 concurrent interviews.
  - This is the input to the Cloud Migration Plan.

## 12. Repository structure (PRD §93 names kept)

```
Hirevion/
├── AI_Recruitment_Platform_Complete_PRD.md · MASTER_IMPLEMENTATION_PLAN.md · CLAUDE.md
├── .claude/settings.json · .githooks/ · .github/workflows/
├── recruitment-platform/          # Next.js: recruiter web app + candidate portal
├── ai-interviewer-desktop/
│   ├── src/                       # auth, interview, coding, proctoring, third-eye, recording, services, i18n, a11y
│   └── src-tauri/                 # src/ + crates/ (security, api-client, screen-capture, recorder, segment-store, uploader,
│                                  #   event-queue, process/window/display/device monitors, lockdown, system-check)
├── third-eye/                     # mobile-browser camera app (Vite + React)
├── backend/                       # uv workspace: core/, api/, realtime/, interview_agent/, vision_agent/, coding/, migrations/
├── workers/                       # media-worker (stream consumers run from hirevion_core via `hv worker`)
├── coding-sandbox/                # sandbox-runner + runner images (python, node, ts, sql) + test harness
├── packages/                      # shared TS: api-client (generated), ui (design system), events, i18n
├── infrastructure/local/          # compose, Caddyfile, livekit/egress config, scripts (cloud/ comes with migration plan)
├── tools/                         # interview-simulator, eval-harness, synthetic-data, load-tests (k6), cost-model
└── docs/                          # architecture/ADRs, superpowers/plans, security/, policies/, runbooks/, api/
```

## 13. Global constraints (every SP inherits these)

- **Platforms:**
  - Desktop: Windows 10 22H2+ and Windows 11, x64 and ARM64, per-user install, WebView2 Evergreen.
  - Web: the latest 2 versions of Chrome, Edge, Firefox and Safari.
  - Third-eye: iOS Safari 16.4+ and the latest 2 versions of Android Chrome.
- **Runtimes:**
  - Python 3.12.
  - Node 24 LTS + pnpm 10; TypeScript in strict mode.
  - Rust stable (MSVC toolchain, edition 2024).
  - PostgreSQL 17 + pgvector; Valkey 8.
  - Exact versions pinned via `uv.lock`, `pnpm-lock.yaml`, `Cargo.lock` and image digests.
- **Licenses:**
  - Allowed: MIT, Apache-2.0, BSD, ISC, Zlib, PSF, and MPL-2.0 unmodified.
  - Not allowed in shipped or served components: AGPL, GPL, SSPL or non-commercial code and models.
  - Dev and infrastructure tools that run as separate processes are exempt: ClamAV, Grafana stack, k6, Semgrep, ffmpeg LGPL build.
  - CI enforces this.
- **API:**
  - `/api/v1` prefix.
  - RFC 9457 errors.
  - Cursor pagination.
  - `Idempotency-Key` on creates.
  - The OpenAPI client is regenerated in CI, and any drift fails the build.
- **Data:**
  - UUIDv7 keys and UTC `timestamptz`.
  - Every organisation-owned table has tenant scope and row-level security.
  - Every §97 action is audited.
- **AI:**
  - Prompts and rubrics are versioned files.
  - Every call is recorded in `ai_invocations`.
  - Blind screening is on by default.
  - Development uses synthetic data; real candidate data reaches AI vendors only after DPAs and opt-outs are in place.
- **Desktop:** ships no master credentials. It uses only short-lived, scoped tokens.
- **UX:**
  - Every string is externalised (en-IN and en-US first).
  - WCAG 2.2 AA.
  - p95 UI interactions under 200 ms.
- **Testing:**
  - TDD.
  - At least 85% line coverage on domain modules.
  - Every authorisation, tenancy and token path is covered by tests.
  - A tenant-isolation suite runs over every endpoint.
- **Git:**
  - Author and committer are `Devaraj-05 <padma.devaraj1800@gmail.com>` only.
  - Never add `Co-Authored-By`, "Generated with Claude Code" or any Claude/Anthropic attribution to commits, PRs, tags or release notes.
  - Conventional Commits.
  - Workflow: short-lived branch → PR → green CI → merge.

## 14. Sub-projects — deliverables, exit criteria, dependencies

Each SP gets its own detailed TDD plan before work starts. "CP" is the checkpoint it lands in (§15).

**SP-00 Foundations & spikes** (CP0; depends on nothing)
- **Deliverables:**
  - The monorepo per §12.
  - Pinned toolchains.
  - The compose stack with all profiles.
  - Caddy local TLS and a hosts script.
  - The `doctor` script.
  - Seed data and synthetic-data generator v1.
  - CI: lint, type-check, tests and build per package, plus security and license scans.
  - Git guards.
  - An ADR template.
- **Spikes** (each result becomes an ADR):
  1. Voice-loop latency through LiveKit with Deepgram (STT/TTS) and Gemini (LLM), measured from end of speech to first AI audio; OpenAI is measured too once its key is set.
  2. Screen capture → 10-second segments at 1080p/15 fps within a CPU budget.
  3. WebView2 media: permission auto-grant, WebCodecs segments, MediaPipe at ≥10 fps.
  4. Self-hosted LiveKit with the desktop and a phone connecting over a tunnel.
- **Exit criteria:** `up` brings every service up healthy; CI is green; every spike's decision is recorded with measured numbers.

**SP-01 Backend core** (CP0; depends on SP-00)
- **Deliverables:**
  - `hirevion_core`: settings, async database, row-level-security context, base model conventions.
  - The Alembic baseline and the core tables: `organizations`, `audit_logs`, `outbox_events`, `usage_events`, `feature_flags`.
  - The outbox publishing to Redis Streams.
  - A hash-chained audit service.
  - The storage service and URL signer (§85 paths).
  - The AI provider layer: six services, the `dev`, `production` and `mock` profiles, `ai_invocations` recording.
  - Metering and a clock-sync endpoint.
  - RFC 9457 errors, pagination, idempotency and rate-limit middleware.
  - OpenTelemetry.
  - The OpenAPI → TypeScript client pipeline.
- **Exit criteria:**
  - The tenant-isolation harness fails any table that lacks row-level security.
  - The outbox delivery test passes.
  - Provider contract tests pass on `mock`, plus a small opt-in live check against Gemini and Deepgram (and OpenAI when its key is set).

**SP-02 Identity & access** (CP1; depends on SP-01 and SP-03). Built in two parts: SP-02a (accounts and sign-in) and SP-02b (organisations and access).
- **Deliverables:**
  - Recruiter authentication (SP-02a):
    - login and logout
    - email verification and password reset
    - session list and revoke
    - lockout and rate limits
    - breached-password check
    - TOTP MFA moved to SP-19 (decided 2026-10-01); until then passwords need 15 characters (§9)
  - User invitations.
  - Organisations: super-admin create and suspend, organisation profile, departments, teams, users.
  - Roles: the 5 predefined §6 roles, custom roles and a permission matrix.
  - Resource scoping.
  - Auditing of login/logout and permission changes.
  - All the related pages.
- **Exit criteria:**
  - The authorisation-matrix tests (every endpoint × every role) pass.
  - The tenant-isolation suite passes.
  - The Playwright authentication tests pass.

**SP-03 Web shell & design system** (CP1; depends on SP-00)
- **Deliverables:**
  - Design tokens and the `packages/ui` components.
  - The app shell with navigation for every §7 IA item.
  - Route skeletons.
  - A data-table framework: server-side filters, saved views, bulk actions.
  - Forms.
  - The notification-centre shell.
  - The dashboard: 10 KPIs and 7 filters, with data wired in as modules land.
  - The pipeline board.
  - i18n and an a11y baseline, with axe in CI.
  - Candidate-portal host routing.
- **Exit criteria:**
  - Every IA route renders behind its guard.
  - axe reports no issues.
  - Keyboard-only navigation works.
  - Light and dark themes both work.

**SP-04 Jobs & documents** (CP1; depends on SP-01–03)
- **Deliverables:**
  - Jobs: 17 fields, 5 statuses, versions, assignment.
  - JD input and pipeline, plus the review/edit UI (§6.6).
  - The resume pipeline (§6.6), including:
    - image formats
    - ZIP uploads
    - quarantine
    - PII masking
    - evidence verification
    - de-duplication
  - Candidates and applications.
  - The skills taxonomy.
  - Embeddings.
  - A processing-status UI with retries.
- **Exit criteria:**
  - 200 synthetic resumes are processed.
  - Extraction F1 meets the target set in SP-00.
  - The EICAR file is quarantined.
  - Injection samples are flagged.
  - No raw Aadhaar number is stored.

**SP-05 Screening & ranking** (CP1; depends on SP-04)
- **Deliverables:** everything in §6.7:
  - configuration with organisation defaults
  - the engine
  - explainable output
  - blind mode
  - workflow statuses
  - all eight §18 actions, single and bulk
  - export
  - override audit
  - candidate lists by pipeline stage
- **Exit criteria:**
  - Rankings are reproducible, with cache hits on repeat runs.
  - Every factor carries verified evidence.
  - Ranking agreement with the labelled set meets the target.
  - Overrides are audited.

**SP-06 Interview configuration** (CP2; depends on SP-05)
- **Deliverables:**
  - Templates (all 13 §21 fields) with immutable versions.
  - The question library: 10 fields, 8 types, versions, the §7 categories.
  - AI question generation (all 6 §23 inputs) with a review/approve workflow.
  - A skill-matrix preview.
  - Organisation interview defaults.
  - Proctoring-level presets.
- **Exit criteria:**
  - Editing a template that's in use creates v+1, while existing interviews keep their pinned version.
  - Generated questions reach the library only after approval.
- **Status, 2026-10-09:** built (PR #4, ADR-0017). It missed the job's "Interview Template" field (PRD §11), which moves to SP-07a.


**SP-07 Assignment, invitations & candidate access** (CP2; depends on SP-06 and SP-02). Built in three parts:
- SP-07a: interviews, assignment, invitations, reminders and rescheduling, plus the job's interview template field.
- SP-07b: the candidate portal and candidate requests.
- SP-07c: candidate desktop auth (DPoP, tokens, one-time codes) and the desktop release registry.
- **Deliverables:**
  - Single and bulk assignment producing all 9 §24 outputs, with a policy snapshot.
  - The interview state machine.
  - Reviewer assignment.
  - Invitations (all 8 §25 contents) with localised templates.
  - Reminders and rescheduling.
  - Candidate accounts.
  - The candidate portal (§6.3).
  - The candidate-auth API: OTP, device registration, DPoP, access/refresh/interview-session tokens, session expiry.
  - The desktop release registry and update manifest.
- **Status, 2026-10-09:** SP-07a built (ADR-0020): interviews, assignment, invitations, reminders and the job's template field. SP-07c built (ADR-0021): desktop sign-in, DPoP-bound tokens, new-device codes and the release registry. SP-07b built (ADR-0022): the candidate portal with its own cookies, the invitation's link, interviews and countdowns, download, notices and requests acted on at `/candidates/requests`.
- **Exit criteria:**
  - An invitation reaches Mailpit and the candidate can set a password.
  - Replay and stolen-token tests fail as they should.
  - An outdated app version is rejected at login.

**SP-08 Desktop foundation** (CP2; depends on SP-07c for real sign-in only). Built in three parts:
- SP-08a: the app, the security and api-client crates, the update gate and system checks. It starts against a stub sign-in, without waiting for SP-07.
- SP-08b: consent, the interview UI shell and the interview path.
- SP-08c: installers, signing, the signed updater, crash reporting and the end-to-end test (ADR-0019).
- **Deliverables:** the §6.4 flow from launch to "Ready", plus completion and exit:
  - The Tauri app with branding.
  - The `security` and `api-client` crates.
  - The update gate.
  - System checks, with results stored.
  - Configurable instructions.
  - Itemised consent and the accommodations request.
  - Fullscreen and lockdown.
  - The interview UI shell: layout, status bar, orb states, captions, timer, controls.
  - The workspace host.
  - The upload-drain screen.
  - NSIS installers for x64 and ARM64.
  - Development code signing.
  - GlitchTip crash reporting.
  - i18n and a11y.
- **Exit criteria:**
  - The tauri-driver end-to-end test (login → checks → consent → ready) passes.
  - The app installs without admin rights.
  - An update is signature-verified.
  - A downgrade is refused.

**SP-09 AI interview engine** (CP2; depends on SP-06 and SP-01; the desktop client from SP-08 only for the CP2 demo). Built in three parts:
- SP-09a: rooms, the voice pipeline, the state machine and the simulator.
- SP-09b: the orchestrator components.
- SP-09c: transcripts, events and crash recovery.

It starts with the interview simulator as its client.
- **Deliverables:** everything in §6.8:
  - Rooms, tokens and agent dispatch.
  - The voice pipeline.
  - All 9 orchestrator components and the state.
  - The ten §35 states.
  - Per-question rules, coverage and provenance tracking.
  - Final-questions FAQ.
  - Text-answer mode.
  - Transcript plus artifacts.
  - The §91 events.
  - Checkpoints, the resume policy and crash recovery.
- **Exit criteria:**
  - Simulator personas complete full interviews.
  - p95 time to first audio ≤ 2.5 s.
  - After an agent is killed, the interview resumes within 10 s with no lost turns.
  - 100% of required skills are covered when time allows.

**SP-10 Evaluation & AI governance** (CP2; depends on SP-09)
- **Deliverables:** everything in §6.9:
  - Both analysers.
  - Skill and final evaluations, including communication, strengths, gaps and follow-up performance.
  - The registry and `ai_invocations`.
  - Pinned re-runs.
  - The eval harness wired into CI.
  - A human-calibration workflow with agreement statistics.
- **Exit criteria:**
  - Every score has at least one verified evidence item.
  - Pinned re-runs reproduce results within tolerance.
  - The eval gate blocks a regressed prompt.

**SP-11 Native Windows monitoring** (CP2; depends on SP-08)
- **Deliverables:** everything in §6.12's native part:
  - Process metadata and the policy matcher.
  - The category catalogue integration.
  - Focus, minimise, fullscreen and exit tracking.
  - Display and device monitors, including virtual devices.
  - Overlay detection.
  - Remote-session and VM detection.
  - Integrity checks.
  - The signed and acknowledged event queue.
  - Heartbeat (Phase 8).
  - Optional shortcut suppression.
- **Exit criteria:**
  - Each scripted test case raises the right event within 2 s:
    - a capture-excluded window
    - a blocked process
    - a renamed blocked binary (caught by hash or signature)
    - plugging in a second monitor
  - A test proves no keystroke content is ever logged.

**SP-12 Recording pipeline** (CP2; depends on SP-08 and SP-01)
- **Deliverables:** everything in §6.11:
  - Capture of every display.
  - Camera and mic segments.
  - The encrypted store and uploader.
  - Acknowledgement with hash verification.
  - Recovery.
  - Evidence snapshots (built with SP-14, which asks for them at event time).
  - Egress (built with SP-13, alongside the third-eye publisher).
  - `media-worker`.
  - Audited playback.
  - `RECORDING_STATUS` events.
  - The §85 layout.
- **Exit criteria:**
  - Chaos tests (kill the app mid-segment, drop the network for 5 minutes, simulate power loss) lose no acknowledged segment, and at most one in-flight segment.
  - Assembled tracks play back in sync, drifting less than 100 ms.

**SP-15a Computer vision core** (CP2; depends on SP-08)
- **Deliverables:**
  - The desktop MediaPipe worker: the five face signals with temporal thresholds.
  - Face-quality guidance during the system check.
  - `vision-agent` v1: OpenCV preprocessing plus server-side verification of face events.
- **Exit criteria:**
  - Absent-face and multiple-face detection meet the precision/recall target on labelled clips.
  - CPU stays within budget while recording.

**SP-13 Third-eye** (CP3; depends on SP-09 and SP-12)
- **Deliverables:**
  - Everything in §6.5.
  - Third-eye in the system check and the live dashboard.
  - Evidence references.
  - LiveKit Egress of the conversation audio and the third-eye video (moved from SP-12).
- **Exit criteria:**
  - Pairing takes 60 s or less on iOS Safari and Android Chrome.
  - Locking the phone raises `THIRD_EYE_DISCONNECTED` within 10 s.
  - A reused token is rejected.
  - Revoking kicks the old device.

**SP-14 Proctoring engine & live monitoring** (CP3; depends on SP-11, SP-12 and SP-09)
- **Deliverables:** everything in §6.12's pipeline:
  - The schema.
  - The severity table.
  - The rule engine with escalation.
  - The evidence manager, with on-demand screen and camera evidence snapshots (moved from SP-12).
  - Server-observed state from LiveKit webhooks, upload continuity and heartbeats.
  - The realtime service and alerts.
  - Nudges.
  - Event review.
  - The live dashboard.
  - Health metrics.
- **Exit criteria:**
  - Events reach the dashboard in under 1 s (p95).
  - A reconnecting dashboard receives the alerts it missed.
  - Dismissed events are audited, but still appear in the report.

**SP-17 Reports, review & Candidate 360** (CP3; depends on SP-10, SP-12 and SP-14)
- **Deliverables:** everything in §6.13:
  - All five report types, as web and PDF.
  - The review workspace.
  - Notes and Hiring Manager input.
  - Score changes.
  - The workflow statuses and the decision.
  - All 13 Candidate 360 tabs.
  - The unified timeline.
  - The pending-review queue.
- **Exit criteria:**
  - The CP3 golden path passes.
  - Every report section is populated from a simulator run.
  - The audit log shows viewed, downloaded, recording-viewed and score-modified entries.

**SP-15b Advanced proctoring** (CP4; depends on SP-15a, SP-13 and SP-14)
- **Deliverables:** everything in §6.12's advanced part:
  - Gaze.
  - Pose and hands.
  - Phone detection.
  - Obstruction.
  - Unexpected person.
  - Third-eye analysis of posture, hands, phone, additional person, secondary screen, workspace and unusual movement.
  - Speech analytics.
  - Detection of additional speakers.
  - Cross-camera correlation.
  - Thresholds that respect accommodations.
- **Exit criteria:**
  - Each detector's precision/recall is reported on the labelled set.
  - False positives per 45-minute session stay within budget.
  - A UI copy review confirms no signal is presented as proof.

**SP-16 Coding interview** (CP4; depends on SP-09 and SP-08)
- **Deliverables:** everything in §6.10:
  - The four runners.
  - The sandbox and `coding-service`.
  - Question and test authoring.
  - Monaco and the whiteboard.
  - `CodingController`.
  - Telemetry.
  - Evaluation.
  - The coding report.
  - The Candidate 360 Coding tab.
- **Exit criteria:**
  - The sandbox-escape suite contains every attack: network access, fork bomb, disk fill, memory bomb, infinite loop, writes outside tmp.
  - All 4 languages run end to end.
  - Time and memory are stored for every run.

**SP-18 Notifications & webhooks** (CP4; depends on SP-01)
- **Deliverables:** everything in §6.14, plus webhook endpoint administration.
- **Exit criteria:**
  - The reference receiver verifies signatures.
  - The retry and dead-letter paths behave as specified.
  - A replayed delivery is rejected.

**SP-19 Enterprise identity** (CP5; depends on SP-02)
- **Deliverables:** everything in §6.15, plus organisation security settings and TOTP MFA (moved from SP-02): encrypted secrets, recovery codes, session rotation on MFA, and enforcement per organisation (required for super and organisation admins by default).
- **Exit criteria:**
  - TOTP enrolment, sign-in with a code, recovery-code sign-in and organisation-enforced MFA pass end-to-end.
  - SAML and OIDC logins work via Keycloak and an Entra test tenant.
  - SCIM compliance tests pass.
  - SAML signature-wrapping attacks are rejected.

**SP-20 ATS integrations & public API** (CP5; depends on SP-05, SP-17 and SP-18)
- **Deliverables:** everything in §6.16.
- **Exit criteria:**
  - Contract tests pass for every adapter.
  - A lint rule blocks provider-specific code outside the adapters.
  - API-key scope tests pass.

**SP-21 Analytics & KPIs** (CP5; depends on SP-05 and SP-17)
- **Deliverables:** everything in §6.17, plus metrics roll-ups.
- **Exit criteria:**
  - Every metric definition is documented and unit-tested against seed data.
  - Every chart passes axe.

**SP-22 Administration & governance** (CP5; depends on SP-02 to SP-17)
- **Deliverables:** everything in §6.18, plus retention, DSR and consent tooling.
- **Exit criteria:**
  - Retention deletes expired data while respecting legal holds, and every deletion is audited.
  - The DSR export bundle is complete.
  - Every policy change is audited.

**SP-23 Production hardening** (CP6; depends on all)
- **Deliverables:**
  - Threat models.
  - ASVS L2 verification.
  - CI security gates.
  - Parser fuzzing.
  - AI-assisted pentest and fixes.
  - Load and capacity tests (`mock` profile) plus local media capacity.
  - Backup/restore and DR drills (local).
  - The §96 dashboards and alerts.
  - WCAG audit, including a manual NVDA pass.
  - Performance budgets.
  - Final code-signing and update pipeline.
  - Support tooling (Phase 11):
    - session diagnostics
    - a desktop log-bundle upload, with the candidate's consent
    - a support flow
  - Runbooks.
  - The cost-model report.
  - The PRD §105 checklist.
- **Exit criteria:**
  - Every CP6 gate is green.
  - The cloud-dependent §105 items are handed to the Cloud Migration Plan with acceptance criteria.

## 15. Checkpoints

A checkpoint is a demo plus quality gates. Lanes, order and priorities are in [PENDING_TASKS.md](PENDING_TASKS.md); progress is in [docs/STATUS.md](docs/STATUS.md).

| CP | Outcome |
|---|---|
| 0 | Stack up; spikes decide the models, capture/encode path and LiveKit networking |
| 1 | Recruiter: job → JD → 200 resumes → evidence-backed ranking → shortlist |
| 2 | Candidate completes a voice interview in the desktop app, with recording, core proctoring and evaluation |
| 3 | Core hiring loop: PRD §104 MVP plus live monitoring, reports and third-eye |
| 4 | Coding interview, advanced proctoring, notifications & webhooks |
| 5 | SSO/SCIM, ATS & public API, analytics, admin & governance, localisation |
| 6 | Hardened: PRD §105 checklist green locally; cost model feeds the Cloud Migration Plan |

**Merging:**
- Each part opens its PR against `main`.
- A lane merges its own green PR by fast-forward, as Devaraj-05.
- Lane B merges any PR a cloud session can't.
- Never use GitHub's merge button, which makes GitHub the committer.

**CI cost:** jobs are path-filtered on branches, so a push runs only the jobs its changes touch; `main` runs everything.

**Shared files across lanes:**
- **Migrations:** one linear Alembic chain, so renumber yours when rebasing onto `main`.
- **Generated files:** regenerate `openapi.json` and `schema.d.ts` after a rebase.
- **Message catalogues:** each lane edits only its own namespace in the message files.
- **Permissions:** the permission catalogue and the authorisation matrix change only in lane A, or in a lane A follow-up.

## 16. Verification & quality gates

- **Every sub-project:**
  - Write the failing test first.
  - Unit and integration tests against real Postgres/Redis in Docker, plus contract tests.
  - Green CI.
  - Code review via `superpowers:requesting-code-review`.
- **Definition of done for every part.** Tightened on 2026-10-09: SP-04a to SP-06 skipped the review, coverage, scans, threat models and traceability below, and those gaps are now catch-up item H0 in [PENDING_TASKS.md](PENDING_TASKS.md). A part is done when all of these hold:
  1. A short plan exists.
  2. Failing tests came first, including for web components.
  3. Lint, types and tests pass locally, plus an end-to-end test of the part's main path.
  4. `/code-review` has run on the diff and its findings are fixed.
  5. The ADR, runbook, Appendix A rows, threat-model section and PENDING_TASKS.md are updated.
  6. A PR is open against `main` and CI is green.

  The CI gates promised below (coverage ≥ 85% on domain modules, Semgrep, Bandit, dependency, container and license scans, the traceability check) go in as H0.4–H0.5, before CP2 rather than at SP-23.
- **Web:**
  - Playwright end-to-end tests for every critical flow, with axe accessibility checks.
  - Vitest component tests.
- **Desktop automated tests:**
  - `cargo test` on the native crates.
  - Windows integration tests: capture → segment files.
  - tauri-driver end-to-end tests.
- **Desktop hardware matrix:** tested manually on:
  - this PC and a low-spec laptop
  - built-in and USB webcams
  - two monitors
  - a Bluetooth headset, switching devices mid-interview
  - Windows 10 22H2 and a Windows N-edition VM
  - a standard (non-admin) user account
  - a throttled network (using clumsy)
- **Interview end-to-end — `tools/interview-simulator`:**
  - A synthetic candidate joins LiveKit.
  - It answers with TTS audio from persona scripts: strong, partial, weak, silent, adversarial, cheating.
  - It emits telemetry and uploads segments.
  - Tests assert the transcript, evaluation, events, recordings and reports.
  - It runs in CI with the `mock` profile and nightly against Gemini and Deepgram.
- **Chaos drills:** each drill must end with complete recordings, the correct events, and the interview resumed. The drills cover all seven §95 failure modes:
  - Drop the network mid-answer.
  - Force a server timeout.
  - Kill the desktop app.
  - Kill the interview agent.
  - Restart LiveKit.
  - Unplug the camera or mic.
  - Disconnect third-eye.
  - Fail a segment upload.
- **AI quality:** eval-harness gates run on every prompt or model change.
- **Security:**
  - Tenant-isolation and authorisation-matrix suites.
  - Semgrep, Bandit, dependency, secret, container and license scans in CI.
  - OWASP ZAP against the local stack.
  - AI-assisted pentest (strix-security skill) at CP3 and CP6.
  - An external pentest right after GA, as you chose.
- **Capacity:** k6 plus the simulator on the `mock` profile measure per-instance capacity for API, WebSocket, workers and agents.
- **PRD traceability:** CI checks that every Appendix A row points at code and tests (a link list maintained per SP).
- **Golden-path acceptance (CP6, the §107 flow):**
  1. The super admin creates an organisation, and the org admin invites a recruiter.
  2. The recruiter creates a job and uploads a JD and 50 resumes, sees the ranking with evidence, and shortlists candidates.
  3. The recruiter builds a template (coding, strict proctoring, third-eye) and sends an invitation.
  4. The candidate installs the signed build, logs in, passes the system check, consents and pairs a phone.
  5. The candidate completes a voice and coding interview while the recruiter monitors live and receives alerts.
  6. Reports are produced as web views and PDF.
  7. The recruiter reviews with evidence links and records a decision.
  8. The webhook is delivered, the audit trail is complete and analytics update.
  9. The retention and DSR jobs are verified.

## 17. Owner actions still open

- **API keys:** put your Gemini and Deepgram keys in the gitignored root `.env` (`uv run hv env-sync` adds any missing settings); the OpenAI key is needed only for production. No GPU is needed.
- **Test devices:**
  - An Android phone and an iPhone for third-eye.
  - A USB webcam.
  - A second monitor.
  - A headset.
  - Ideally a low-spec Windows laptop.
- **Long-lead items for cloud GA** (start now; they don't block local work):
  - An OV code-signing certificate for your legal entity via a cloud HSM (validation takes days).
  - A domain name.
  - OpenAI: check your organisation's usage tier and rate limits (they rise with spend and account age), set a monthly budget, and request zero data retention if eligible.
  - Deepgram: set a budget and opt out of model improvement.
  - Gemini: keep the key on the paid tier (its prompts aren't used to improve Google's products) and set a budget.
  - Sign DPAs with Google (Gemini), OpenAI and Deepgram before any real candidate data is used. ElevenLabs/Cartesia only if we add them later.
  - Counsel review of the `docs/policies/` drafts.
  - Booking the external pentest.

## 18. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Solo capacity vs full scope | Riskiest work first (spikes on days 1–2), parallel subagents, checkpoint demos and a weekly re-plan. Gates never move; dates do. |
| AI vendor latency from India, rate limits and cost | SP-00 latency benchmark, streaming everywhere, per-route model choice, fallbacks, metering with budgets, and the `mock` profile for CI and load tests. |
| Native capture/encoding complexity | Spike it first; DXGI fallback; software H.264 encoder; Media Feature Pack guidance on N editions. |
| LiveKit and phone networking on Docker Desktop | Single-port UDP mux with TCP fallback; tunnel for HTTPS signalling; same-Wi-Fi rule during development. |
| AI scoring quality and fairness | Evidence verification, eval harness, calibration with humans, blind mode, adverse-impact monitoring, no automatic decisions. |
| Proctoring false positives | Temporal thresholds, server-side verification, configurable severity, a review workflow, precision/recall targets on labelled video. |
| Security of a solo-built system | ASVS L2 checklist, automated scans, isolation suites, AI pentest at CP3/CP6. The external pentest comes right after GA, as you chose; book it in advance and treat its critical findings as release blockers. |
| SmartScreen / antivirus false positives | Sign early and submit binaries to Microsoft. No code injection; keyboard hooks only when a policy requires them. |
| DPDP compliance | Consent, DSR and retention built in; counsel review of policies; a sub-processor register. |
| Single-person knowledge risk | ADRs, runbooks, CLAUDE.md conventions, and specs and plans kept in the repo. |
| Unmerged stacked PRs (four at once, 2026-10-09) | Merge daily, in order; stack at most one deep; open each PR against `main`. |
| No real-model validation yet (the Gemini key has been invalid since 2026-10-03) | Fix the key before SP-09. Run the resume and screening evaluations and the live provider tests, and tune prompts before building the interview engine on top of them. |
| The desktop lane started late (no native work since the SP-00 spikes) | Start SP-08a now against a stub sign-in, so capture, recording and proctoring risks surface before CP2. |
| Merge conflicts once lanes run in parallel | The shared-file rules in §15. Rebase onto `main` before each PR, then regenerate the generated files. |

---

## Appendix A — PRD traceability checklist (§1–§109)

Every PRD section maps to where it is delivered. An item marked "Cloud plan" is deferred to the Cloud Migration Plan by your instruction.

| § | PRD requirement (all enumerated items) | Delivered by |
|---|---|---|
| 1 | End-to-end flow; the two applications and third-eye | Whole plan; SP-04 → SP-17 |
| 2 | 8 vision pillars; hiring decisions stay under human control | §3.2(1), SP-05, SP-10, SP-17 |
| 3 | 18 goals, including interview, **coding** and proctoring reports | SP-04–17 (coding report in SP-16/17); security/tenancy/RBAC/audit/governance in SP-01, 02, 10, 23 |
| 4 | Scope boundaries | §4 |
| 5 | Product architecture: web, desktop, third-eye and shared-backend components | §1, §5, §6 |
| 6 | Six roles and their responsibilities, including Hiring Manager input and reviewers on assigned interviews | SP-02 (roles and scopes), SP-07 (reviewers), SP-17 (HM input), SP-22 (super admin) |
| 7 | IA: Dashboard; Jobs ×7; Candidates ×6; Interviews ×4; Question Library ×5; Reports ×4; Administration ×7 | SP-03 plus the owning SPs (§6.2) |
| 8 | Web: email/password, Entra ID, OIDC, SAML, MFA, sessions, password reset, RBAC, rate limiting | SP-02a (email/password, sessions, password reset, rate limiting), SP-02b (RBAC), SP-19 (Entra ID, OIDC, SAML, MFA) |
| 8 | Desktop: email/password, short-lived token, interview session token, device/session binding, expiry; no master credentials | SP-07c (ADR-0021: DPoP-bound access, refresh and session tokens, `test_candidate_auth_api.py`), SP-08, §13 |
| 9 | Organisation profile, departments, teams, users, roles, permissions | SP-02 |
| 9 | Branding, default screening/interview config, proctoring policies, AI config, retention, integrations | SP-05 (screening defaults), SP-06 (interview defaults and proctoring presets), SP-22, SP-20 |
| 10 | 10 dashboard KPIs and 7 filters | SP-03, SP-21 (KPIs wired from real data as modules land: catch-up H0.2) |
| 11 | 17 job fields; 5 statuses | SP-04 (Screening Configuration field → SP-05; Interview Template field → SP-07a: `jobs.interview_template_id`, the job form's choice) |
| 12 | JD formats (PDF, DOCX, TXT, text); 10-step pipeline; 8 extracted items; recruiter review/edit | SP-04 (§6.6) |
| 13 | Single, bulk, PDF, DOCX, TXT, image/OCR; 10-step pipeline including malware scan | SP-04b (§6.6; ZIP bulk upload, per-entry scanning, ADR-0015) |
| 14 | 16 parsed fields; evidence references | SP-04b (page, section and verified quote per item; F1 in `docs/evals/`) |
| 15 | 4 inputs; 9 evaluation factors; 6 combination methods | SP-05 (§6.7, ADR-0016) |
| 16 | 9 ranking output fields; explainable, with evidence per factor | SP-05 (evidence drawer; NDCG in `docs/evals/`) |
| 17 | Configurable weights; Required/Preferred/Optional skills | SP-05, SP-22 (organisation defaults) |
| 18 | 6 workflow stages; 8 actions; override audit | SP-05 (7 actions), SP-07a ("Create interview" on the ranking, single and bulk) |
| 19 | 13 candidate-profile sections | SP-04b (profile, resume, parsed profile, applications, jobs), SP-05, SP-17 |
| 20 | 13 Candidate 360 tabs | SP-17 |
| 21 | 13 template fields; example weights and difficulty distribution | SP-06 (ADR-0017; skill-matrix preview; built-in defaults 20/50/30) |
| 22 | 10 question fields; 8 question types | SP-06 (versioned library, §7 categories, approval; time limits and follow-up rules honoured in SP-09) |
| 23 | AI question generation from 6 inputs; review before reuse | SP-06 (`interviews.generation`: drafts approved by a recruiter; candidate work history only, never contact details) |
| 24 | Assignment: 3 inputs → 9 system fields | SP-07a (ADR-0020: `hirevion_core.interviews.assignment`, the policy snapshot, `test_interview_assignment.py`) |
| 25 | 8 invitation contents | SP-07a (`interviews.invitations`, en-IN/en-US templates, the Mailpit test and `e2e/auth/interviews.spec.ts`), SP-07b (ADR-0022: the pages it links to: `/invitation/`, download, notices, requests, forgot password; `e2e/auth/portal.spec.ts`) |
| 26 | 9 startup steps (`AI-Interview.exe`) | SP-08 (the update gate with Update now, the signed updater and downgrade refusal: SP-08c, ADR-0019, `tests/updater.rs`; the version check's server side, the release registry and update manifest: SP-07c) |
| 27 | Tauri, React, TypeScript, Rust, Monaco | SP-08 (the per-user NSIS installers, development signing and GlitchTip crash reports: SP-08c, ADR-0019; the tauri-driver test `e2e/desktop.e2e.mjs`), SP-16 |
| 28 | 6 login verifications; short-lived credentials | SP-07c (`candidate_access.service`, the six checks in order with their codes), SP-08 |
| 29 | 11 system checks; policy-driven mandatory checks | SP-08 (the checks on the device), SP-09 (`interview_session.preparation.record_system_check`, mandatory checks from the policy and accommodations: `test_conductor.py`) |
| 30 | 6 instructions (configurable); 10 consent items | SP-08, SP-09 (the briefing: `interview_session.briefing`, the organisation's instructions in Administration → Organisation, itemised consents against `NOTICE_VERSION`), SP-22 |
| 31 | Fullscreen; 5 monitored states | SP-08, SP-11 |
| 32 | UI layout, timer, orb, transcript, editor (language, Run, Submit), status bar, non-coding workspace | SP-08, SP-09 (`hv.state`: voice, question, time left, workspace; `POST /workspace`), SP-16 |
| 33 | 6 voice states; streaming STT/TTS | SP-09 (ADR-0030: the agent's `hv.state` voice states incl. `error`; Deepgram streaming STT/TTS through LiveKit, `hirevion_interview_agent.agent`) |
| 34 | No single giant prompt; 12 state fields; 9 components | SP-09 (`hirevion_core.engine`: `state.InterviewState`, the nine components, `orchestrator.py`; `tests/engine/`), SP-16 (CodingController's runs and grading) |
| 35 | 10 state-machine states | SP-09 (§6.8; `engine.state.STAGES` recorded with times; `test_orchestrator.py`) |
| 36 | Resume-based questions with internal source reference | SP-09 (`engine.skills.resume_hooks`, `interview_questions.source`/`source_ref`, the transcript page's source lines) |
| 37 | JD skill coverage tracked | SP-09 (`engine.completion.CompletionEvaluator`, required JD skills added by `SkillMatrixBuilder`; coverage in `GET /interviews/{id}/transcript`; every persona covers them in `test_interview_session_api.py`) |
| 38 | 5 answer analyses; 4 adaptive behaviours | SP-09 (`engine.analysis.AnswerAnalyzer`, `engine.followups.FollowUpGenerator`), SP-10 (the async evaluator) |
| 39 | Easy/Medium/Hard adaptive, keeping coverage | SP-09 (`engine.difficulty.DifficultyController`, the per-skill ladder) |
| 40 | 5 time signals; plan shrinks while keeping important skills | SP-09 (`engine.timing.TimeController`: deadline, remaining, question limits, coding time; `shrink` keeps uncovered required skills) |
| 41 | 6 transcript-segment fields | SP-09 (`transcript_segments`, partitioned; `interview_session.transcripts.segment`) |
| 42 | TTS: low latency, streaming, interruption, state tracking, failure handling | SP-09 (the agent's acknowledgement while analysing, interruptible speech, the pronunciation lexicon in `tts_node`, the `error` state; `hv-voice-bench` measures p95) |
| 43 | Complete two-sided transcript | SP-09 (both speakers per turn; JSON/VTT/TXT artifacts by the `interview.completed` consumer; the interview page's transcript) |
| 44 | 8 evaluation dimensions, with evidence | SP-10 (`evaluation.scoring.QuestionEvaluator`, `evaluation.evidence`, `question_evaluations`; `test_question_evaluator.py`, ADR-0031) |
| 45 | Coding flow; Python, JavaScript, TypeScript, SQL | SP-16 |
| 46 | Never on API servers; queue; 6 limits; destroyed after each run | SP-16 |
| 47 | 8 coding-evaluation criteria; 5 stored artifacts | SP-16 |
| 48 | 8 telemetry events; no unnecessary global keystrokes | SP-16 |
| 49 | 6 camera uses; 5 microphone uses | SP-09, SP-12, SP-13 (conversation-audio Egress), SP-15a, SP-15b |
| 50 | Native screen capture; segmented; continuous upload | SP-12 (device: lane B; server, D2: `hirevion_core.recordings.segments` write-only per-segment upload URLs, `hirevion_core.recordings.assembly` joining each track with ffmpeg and `hirevion_core.recordings.timeline` the timeline map; `test_recordings_api.py`, `test_recording_assembly.py`) |
| 51 | Encrypted buffer → queue → retry → server acknowledgement; crash/network recovery | SP-12 (device queue: lane B; server, D2: hash-verified acknowledgement and the recovery listing in `hirevion_core.recordings.segments`, continuity events in `hirevion_core.recordings.monitor`; `test_recordings_api.py`, `test_recording_monitor.py`) |
| 52 | Third-eye flow; 5 token properties | SP-13 |
| 53 | 7 third-eye signals, as evidence only | SP-15b (plus SP-13 transport) |
| 54 | 7 sources; 8-stage pipeline | SP-14 (delivered, C5: `hirevion_core.proctoring.normaliser`, `hirevion_core.proctoring.aggregator`, `hirevion_core.proctoring.rules`, `hirevion_core.proctoring.evidence`, `hirevion_core.proctoring.service`; the report is `GET /proctoring/{interview_id}`; `test_rules.py`, `test_pipeline.py`, `test_proctor_engine.py`) |
| 55 | 14 events | SP-11, SP-12, SP-13, SP-14 (delivered: all 14 plus the §6.12 additions and `DEVICE_CHANGE`, `UNEXPECTED_WINDOW`, `TELEMETRY_GAP`, `THIRD_EYE_RECONNECTED`, in `hirevion_core.proctoring.catalogue`), SP-15a/b (§6.12 table) |
| 56 | OpenCV, MediaPipe, ONNX Runtime; 5 face signals; temporal thresholds | SP-15a |
| 57 | Gaze pipeline; 3 gaze events; not proof | SP-15b |
| 58 | 4 pose/hand signals plus editor correlation | SP-15b |
| 59 | 6 speech measures; not proof | SP-15b |
| 60 | 6 process-metadata fields; Rust + Windows APIs | SP-11 |
| 61 | Blocked/allowed apps and categories; 6 detection attributes | SP-11, SP-22 |
| 62 | 4 focus detections; 4 stored fields | SP-11 |
| 63 | 5 display/device changes, as evidence | SP-11, SP-13 |
| 64 | INFO/WARNING/CRITICAL; configurable; examples | SP-14 (delivered: the §6.12 table, escalation and gaze in `hirevion_core.proctoring.rules`, pinned per session by `hirevion_core.proctoring.policy`; `test_rules.py`), SP-22 (the policy editor) |
| 65 | Realtime path; 8 things the recruiter sees | SP-14 (delivered, Streams instead of Pub/Sub, per §3.2: `PROCTOR_EVENT`, `PROCTOR_STATUS` and `PROCTOR_REVIEW` on `hv:rt:interview:{id}`, `/ws/proctoring/{id}`, `hirevion_core.proctoring.live`; `test_proctoring_api.py`) |
| 66 | Live dashboard layout | SP-14 (delivered: `monitoring-panel.tsx` on the interview page, `proctoring-state.ts`; `proctoring.test.tsx`; the camera, screen and third-eye video tiles need `POST /proctoring/{interview_id}/observe`'s token and wait for the media player) |
| 67 | 7 evidence types; JSON schema | SP-12, SP-14 (delivered: the schema and `proctor_evidence` in `hirevion_core.proctoring.evidence`, snapshots asked for at CRITICAL events and answered through `/proctoring/evidence-uploads`; `test_proctoring_api.py`) |
| 68 | 14 proctoring-report sections; no single score | SP-17 |
| 69 | 13 interview-report sections | SP-17 |
| 70 | Per-skill final evaluation, with evidence | SP-10 (`evaluation.aggregate`, `GET /interviews/{id}/evaluation`; `test_aggregate.py`; the coding slot is SP-16) |
| 71 | 11 recruiter-review actions | SP-17 |
| 72 | 9 hiring statuses, audited | SP-17 |
| 73 | 12 analytics | SP-21 |
| 74 | 9 funnel stages | SP-21 |
| 75 | 3 channels; 8 notification events | SP-18 |
| 76 | 8 ATS/integration targets; no provider logic in core | SP-20 |
| 77 | 9 webhook events; 5 security measures | SP-18 |
| 78 | AIProvider (5) and 5 services | SP-01 |
| 79 | 8 governance fields | SP-10 (`ai_invocations` fields set by `evaluation.service`, pinned re-runs `hv eval-rerun`, the gate `hv eval-interviews`; `test_evaluation_service.py`, `test_harness.py`) |
| 80 | Immutable template versions; interviews pin a version | SP-06 (insert-only version tables for templates and questions), SP-07a (interviews pin `(template_id, template_version)` and a policy snapshot) |
| 81 | Tenant scoping; server-side authorisation | SP-01, SP-02 |
| 82 | 15 security requirements; SOC 2 / ISO 27001 target | §9, SP-01/02/07/08/12/16/23 (certifications need the cloud and an audit period) |
| 83 | 10 disclosures; 6 policies | SP-07b (ADR-0022: `candidate_portal.notices` serves the ten disclosures and six policies, `markdown.tsx`, `test_portal_api.py`), SP-08, SP-09 (the itemised notice per policy, consents stored per purpose), SP-22, `docs/policies/` (drafts: H0.7) |
| 84 | Organisation-configurable retention (6 classes) | SP-22 |
| 85 | Postgres (8), Redis (5), Blob (9); path layout; short-lived SAS | SP-01, SP-12 (D2: recordings under `{org}/interviews/{id}/{screen,camera,audio}/` by `hirevion_core.recordings.tracks`; 15-minute write-only and 5-minute read-only SAS; `test_recording_tracks.py`) |
| 86 | Gateway, Recruitment/Interview/Proctor APIs, orchestrator, workers | SP-01 (Caddy locally; route groups), SP-09 |
| 87 | api/worker/realtime/coding services; 15 logical modules | SP-00, SP-01 (§6.1) |
| 88 | Azure production architecture | Cloud plan |
| 89 | Every core table | §7; each owning SP |
| 90 | 20 API groups; the screening, interview and proctoring example endpoints | §8; owning SPs (SP-09: `/interviews/{id}/start`, `/answer`, `/complete`, `/transcript`; SP-14: `/proctoring/session`, `/events`, `/heartbeat`, `/evidence-uploads`, `GET /proctoring/{interview_id}` and `/evidence`) |
| 91 | 3 WebSocket channels; 10 events | SP-09 (`/ws/interviews/{id}`; `AI_SPEAKING`, `CANDIDATE_SPEAKING`, `QUESTION_STARTED`, `ANSWER_RECEIVED`, `INTERVIEW_COMPLETED` on `hv:rt:interview:{id}`), SP-12 (D2: `RECORDING_STATUS` on the same stream from `hirevion_core.recordings.monitor` and `hirevion_core.recordings.assembly`), SP-13, SP-14 (delivered, `/ws/proctoring/{id}` and `PROCTOR_EVENT`; `/ws/recruiter` and the other events with their owners), SP-16 |
| 92 | Third-eye realtime path | SP-13 |
| 93 | Repository structure | SP-00 (§12) |
| 94 | Technology stack (local parts) | §2; Azure part in the Cloud plan |
| 95 | 7 failure modes; 5 mechanisms | SP-08, 09, 11, 12, 13 + chaos drills (§16) |
| 96 | 14 observability signals | SP-01, SP-23 |
| 97 | 16 audited actions | SP-01 plus the owning SPs (SP-12 D2: "recording viewed" audited on every playback listing, `test_recording_playback_api.py`); audit-coverage test in SP-23 |
| 98 | Unified timeline (8 sources) | SP-17 |
| 99 | 5 configurable candidate-visible items; internal reports stay confidential | SP-17, SP-07b (the portal's report page lists the five items until SP-17 fills it; internal reports never reach `/api/v1/portal/`) |
| 100 | 10 → 10k growth path; independent scaling; performance targets | Architecture (§5–6), SP-23 local capacity; cloud-scale tests in the Cloud plan |
| 101 | Web: 4 accessibility items; desktop: 4; proctoring adjustments for accommodations | SP-03, SP-08, SP-22, SP-23 |
| 102 | 4 kinds of externalised text; English first | SP-03, SP-22 |
| 103 | Phases 1–11 | P1 → SP-02/04/05 · P2 → SP-06/07 · P3 → SP-08/09 · P4 → SP-09/10/17 · P5 → SP-16 · P6 → SP-11/12/14/15a · P7 → SP-13 · P8 → SP-11 · P9 → SP-15b · P10 → SP-18–22 · P11 → SP-23 |
| 104 | MVP (platform, desktop, third-eye, proctoring lists) | CP3 |
| 105 | Production Definition of Done (30 items) | CP6 locally; cloud-dependent items in the Cloud plan |
| 106 | 20 KPIs | SP-21, SP-23 |
| 107 | End-to-end product flow | Golden-path acceptance test (§16) |
| 108 | Final architecture, including the desktop's local CV engine | §5, §6.4, §6.12 |
| 109 | Architectural boundary statement | §1 |
