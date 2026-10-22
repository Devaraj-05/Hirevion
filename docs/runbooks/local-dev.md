# Local development runbook

Everything Hirevion needs runs on your PC in Docker Desktop, plus hosted AI APIs
(Gemini and Deepgram in development). This page covers first-time setup, daily use and
fixes for common problems.

## First-time setup

1. `git config core.hooksPath .githooks`
2. `uv sync`
3. `uv run hv init-env`, then add `GEMINI_API_KEY` and `DEEPGRAM_API_KEY` to `.env`.
   After pulling new changes, `uv run hv env-sync` adds any new settings (your values are kept).
4. `uv run hv up`. The first start takes a few minutes while ClamAV downloads virus signatures.
5. `uv run hv hosts`. Windows asks once for admin rights. Browsers resolve `*.hirevion.localhost`
   by themselves, but Python, Node and Rust need these hosts-file entries.
6. `uv run hv trust-ca`. Windows asks you to confirm installing Caddy's local root certificate,
   which makes `https://*.hirevion.localhost` trusted in Edge, Chrome and the desktop app.
7. `uv run hv doctor`, then `uv run hv smoke`. Every line should say `ok`.
8. `uv run hv migrate`. It creates the database roles and applies the migrations.
9. `uv run hv storage-init`. It creates the private blob container and lets the web apps upload to it.

## Daily commands

| Command | What it does |
|---|---|
| `uv run hv up` | Starts core, edge and media services and waits until they're healthy |
| `uv run hv up --obs` | Also starts Grafana (traces, logs, metrics) and GlitchTip (errors) |
| `uv run hv ps` | Shows containers and their health |
| `uv run hv logs [service]` | Follows logs, for example `uv run hv logs livekit` |
| `uv run hv smoke [--obs]` | Proves each service works with a real round-trip |
| `uv run hv migrate [--database NAME]` | Creates the database roles, applies migrations and adds upcoming partitions |
| `uv run hv api [--port 8000] [--no-reload]` | Runs the API on `127.0.0.1:8000`, reloading when backend code changes |
| `uv run hv openapi [--check]` | Writes (or checks) `packages/api-client/openapi.json` |
| `uv run hv storage-init` | Creates the blob container and the CORS rules for browser uploads |
| `uv run hv down` | Stops everything; data is kept |
| `uv run hv reset` | Stops everything and deletes all local data (asks first) |

## Services and addresses

| Service | Profile | From your PC | Through Caddy (HTTPS) |
|---|---|---|---|
| PostgreSQL 17 + pgvector | core | `127.0.0.1:5432` (databases `hirevion`, `hirevion_test`, `glitchtip`) | — |
| Valkey (Redis-compatible) | core | `127.0.0.1:6379` (password in `.env`) | — |
| Azurite blob storage | core | `http://127.0.0.1:10000/<AZURE_STORAGE_ACCOUNT>` | `https://storage.hirevion.localhost` |
| ClamAV | core | `127.0.0.1:3310` | — |
| Mailpit | core | SMTP `127.0.0.1:1025`, UI `http://127.0.0.1:8025` | `https://mail.hirevion.localhost` |
| LiveKit | media | `ws://127.0.0.1:7880`; media on 7881/tcp and 7882/udp | `wss://livekit.hirevion.localhost` |
| Caddy | edge | 80 / 443 | all `*.hirevion.localhost` sites |
| Grafana (otel-lgtm) | obs | `http://127.0.0.1:3001`; OTLP 4317 (gRPC), 4318 (HTTP) | `https://grafana.hirevion.localhost` |
| GlitchTip | obs | `http://127.0.0.1:8100` | `https://errors.hirevion.localhost` |

The application sites (`app.`, `candidate.`, `api.`, `ws.`, `eye.`) point at ports 3000, 5174, 8000
and 8001 on your PC. `api.` and `app.`'s `/api/*` answer while `uv run hv api` runs; the others
answer once later sub-projects start those apps.

## Database: migrations, roles and tests

The design is in [ADR-0009](../architecture/adr/0009-tenancy-and-data-foundations.md).

- **Roles.**
  - Services connect as `hirevion_app`, which row-level security always applies to.
  - The outbox relay connects as `hirevion_relay`.
  - Their passwords are `POSTGRES_APP_PASSWORD` and `POSTGRES_RELAY_PASSWORD` in `.env` (`hv env-sync` generates them).
  - `hv migrate` creates the roles, or resets them to match `.env`. Only migrations use the admin role (`POSTGRES_USER`).
- **Migrate.** Run `uv run hv migrate` after pulling changes, and at least every two months: it also creates the next months' partitions of `audit_logs` and `usage_events`.
- **Add a migration.**
  - Run `uv run alembic -c backend/migrations/alembic.ini revision -m "add jobs"` and write it by hand.
  - A new tenant table needs `tenant_policy_sql()` and explicit `grant_sql()` calls.
  - Update the model in `hirevion_core.models` to match.
  - `test_models_match_migrations` and the isolation harness (`test_baseline_has_no_isolation_problems`) catch mistakes.
- **Tests.**
  - `uv run pytest` includes the `db` tests. They rebuild the `hirevion_test` database's schema and use Valkey database 15, so the stack must be up.
  - `uv run pytest -m "not db"` runs everything else.
- **Look inside.** `docker exec -it hirevion-postgres-1 psql -U hirevion hirevion` (the user is `POSTGRES_USER`). As the admin you bypass row-level security; to see what a tenant sees, run:

  ```sql
  SET ROLE hirevion_app;
  SELECT set_config('app.org_id', '<org id>', false);
  ```

## API (`backend/api`)

The conventions are in [ADR-0010](../architecture/adr/0010-api-conventions.md); client developers
read [docs/api/conventions.md](../api/conventions.md).

- **Run it.** `uv run hv migrate` once, then `uv run hv api`. Try:
  - `https://api.hirevion.localhost/api/v1/health/ready`;
  - the interactive docs at `https://api.hirevion.localhost/api/v1/docs`.

  Windows' `curl.exe` needs `--ssl-no-revoke` for the local certificate authority; browsers don't.
- **Traces, metrics and logs.** Start `uv run hv up --obs` and set `OTEL_SDK_DISABLED=false` in
  `.env`. Then open Grafana → Explore → Tempo and search `{resource.service.name="hirevion-api"}`.
  Health probes are never traced.
- **After changing a route or a response model**, regenerate the client contract. CI fails until
  both files are committed:

  ```sh
  uv run hv openapi
  pnpm --filter @hirevion/api-codegen generate
  ```

- **Container image.** `docker build -f backend/api/Dockerfile -t hirevion-api .` builds what CI builds.

## Storage and AI (`hirevion_core.storage`, `hirevion_core.ai`)

The design is in [ADR-0011](../architecture/adr/0011-storage-ai-metering.md).

- **Signed URLs.** Upload and download URLs point at `https://storage.hirevion.localhost`. `hv smoke` checks one round trip through Caddy (`signed-storage`).
- **AI profile.**
  - `HV_AI_PROFILE=dev` uses Gemini and Deepgram with the keys in `.env`.
  - `mock` needs no network (tests use it).
  - Model names are the `HV_LLM_MODEL_*`, `HV_EMBEDDING_MODEL` and `HV_VISION_MODEL` settings.
- **Live checks** (a few cents): `uv run pytest --live backend/core/tests/live`. Add `OPENAI_API_KEY` and `HV_OPENAI_TEST_MODEL` to check OpenAI too.
- **Spend.** Every call is a row in `ai_invocations`. For this month's cost per organisation:

  ```sql
  SELECT organization_id, service, count(*), sum(cost_usd)
  FROM ai_invocations
  WHERE occurred_at >= date_trunc('month', now())
  GROUP BY 1, 2;
  ```

- **Budget.** Calls stop with `AiBudgetExceeded` once an organisation's monthly spend reaches its `ai.cost.usd` quota, or `HV_AI_MONTHLY_BUDGET_USD` when it has none.
- **Prices** live in `backend/core/src/hirevion_core/ai/prices.yaml`, each with its source and date. Add a model there when you configure it; until then its calls record no cost.

## Recordings (`hirevion_core.recordings`, SP-12 server side)

The contract is [recordings.md](../api/contracts/recordings.md); the plan is `docs/superpowers/plans/2026-10-10-sp-12-server-recording.md`.

- **What runs where:**
  - The desktop's routes (`/recordings/segments`, `.../ack`, `/recordings/interviews/{id}/segments`) are in `hv api`.
  - The media worker (assembly and the continuity monitor) runs inside `hv api` (`HV_API_RUN_WORKERS=true`) or alone with `uv run hv worker`.
  - Reviewers play recordings back at `GET /interviews/{id}/recordings` (`reports.interview.view`; each viewing is audited as `recording.viewed`).
- **ffmpeg.** The worker runs ffmpeg as a separate process to join a track's segments (concat demuxer, no re-encoding).
  - Install it: `winget install Gyan.FFmpeg` on Windows, `sudo apt-get install ffmpeg` on Linux and in CI. `HV_FFMPEG_PATH` names a binary that isn't on `PATH`.
  - Without it nothing crashes: the worker logs one warning and the tracks stay `assembly-pending` with the note `ffmpeg-missing`, retried every 10 minutes. Install it and they are built.
  - `uv run pytest backend/core/tests/test_ffmpeg_integration.py` runs the real thing when ffmpeg is found, and skips otherwise.
- **Settings** (`HV_` prefix, all optional): `FFMPEG_PATH`, `FFMPEG_TIMEOUT_SECONDS` (900), `RECORDING_SETTLE_SECONDS` (120: how long a track waits for segments whose URL was asked for but that aren't acknowledged), `RECORDING_ASSEMBLY_ATTEMPTS` (5), `RECORDING_POLL_SECONDS` (15) and `RECORDING_MONITOR_SECONDS` (10).
- **Where the files go** (PRD §85), under `{org}/interviews/{id}/`:
  - `screen/screen-1-000017.mp4` is a segment; `screen/screen-1-full.mp4` and `screen/screen-1-timeline.json` are the assembled file and its map;
  - `camera/` for the camera; the microphone's files are in `audio/` as `mic-…`.
- **Watching an interview:**

  ```sql
  SELECT track, status, first_seq, last_seq, stalled_since, note, attempts, duration_ms, gaps
  FROM recordings WHERE interview_id = '<uuid>' ORDER BY track;
  SELECT track, seq, state, attempts FROM recording_segments
  WHERE interview_id = '<uuid>' AND state <> 'acknowledged' ORDER BY track, seq;
  ```

  - The live `RECORDING_STATUS` events are on the interview's stream: `redis-cli XRANGE hv:rt:interview:<uuid> - +`.
  - Gaps are the outbox topic `recording.gap` (stream `hv:events:recording.gap`), for the proctoring engine.
- **Statuses.**
  - `recording` while the interview runs.
  - `assembly-pending` once it ends: it waits for in-flight uploads, for ffmpeg, or for a backoff after a failure (`note` says which).
  - `assembling`; a worker that died leaves it, and another takes it over after 30 minutes.
  - `assembled`, or `failed` (after 5 attempts, or with nothing acknowledged: `note` says why).
- **Build a track again** (after fixing ffmpeg, say): `UPDATE recordings SET status = 'assembly-pending', attempts = 0, next_attempt_at = NULL WHERE interview_id = '<uuid>' AND track = '<track>';`. A segment acknowledged after the interview ended does this by itself.
- **Chaos by hand.** Start an interview on the desktop, then kill it, or drop the network for a few minutes. The server's `missing` list (`GET /recordings/interviews/{id}/segments`) and a `recording.gap` event show the hole; the next launch uploads what the desktop still holds.

## Voice agent and latency benchmark

The interviewer (`backend/interview_agent`) is a LiveKit Agents worker: Deepgram speech-to-text
and text-to-speech and LiveKit's local turn detector, with the interview engine deciding every
turn (see "The interview" below). Settings come from `HV_*` in `.env` and are read at the start
of each session.

1. `uv run python -m hirevion_interview_agent.agent download-files` once. It fetches the voice
   detector and, with `HV_TURN_DETECTION=multilingual`, the turn-detector model (about 70 MB).
2. `uv run python -m hirevion_interview_agent.agent dev` with `uv run hv up --media` already
   running. Restart it after changing agent code or `HV_TURN_DETECTION`.
3. `uv run hv-voice-bench --turns 20`, with `uv run hv api` running and `hv seed-identity` done,
   seeds a voice interview, starts it like the desktop app (so the API dispatches the
   interviewer) and plays a synthetic candidate. It prints the time from the end of each answer
   to the agent's first audio (p50/p95; SP-09's target is p95 ≤ 2.5 s), with the agent's own
   stage breakdown.

`hv env-sync` only adds missing settings; it never changes values you already have. When an
ADR changes a default, update the `HV_*` line in `.env` yourself. For example, ADR-0005 replaced
`HV_LLM_MODEL_FAST=gemini-2.5-flash`, which Google no longer serves to new accounts.

If the benchmark says the agent never spoke, LiveKit didn't hand the room to the worker: check
that the worker logged `registered worker`. LiveKit Agents' default measures the whole PC's CPU
and stops taking sessions when it is busy; this agent reports sessions in use instead
(`HV_AGENT_MAX_SESSIONS`).

## Web app (`recruitment-platform`)

One Next.js app serves the Recruitment Platform (`app.`) and the candidate portal (`candidate.`).
How it is put together is in [ADR-0012](../architecture/adr/0012-web-app-architecture.md).

- **Run it.** `pnpm --filter @hirevion/recruitment-platform dev`, then open
  `https://app.hirevion.localhost` and `https://candidate.hirevion.localhost` (through Caddy), or
  `http://localhost:3000` for the recruiter host alone.
- **Sign in.** `/login` signs in against the API (see [Sign in locally](#sign-in-locally)). Under
  `next dev` it also offers a development session per role, which needs no API; switch roles from
  the account menu (top right). Set `HV_WEB_DEV_TOOLS=false` to see the app without them;
  production refuses to start with them on.
- **Component gallery.** `/dev/ui` on the recruiter host shows every design-system component in
  both themes. It is a 404 without the development tools.
- **Keyboard.** Ctrl+K (⌘K) opens the page search; `g` then `d`, `j`, `c`, `i`, `q` or `r` goes to
  Dashboard, Jobs, Candidates, Interviews, Questions or Reports.
- **Settings** (environment variables, all optional locally):

  | Variable | Default | Meaning |
  |---|---|---|
  | `HV_WEB_DEV_TOOLS` | on under `next dev` | Development sessions and the gallery |
  | `HV_API_INTERNAL_URL` | `http://127.0.0.1:8000` | Where the server asks the API for the session |
  | `HV_WEB_RECRUITER_HOSTS` | `app.hirevion.localhost,localhost,127.0.0.1,::1` | Hosts served the recruiter app |
  | `HV_WEB_PORTAL_HOSTS` | `candidate.hirevion.localhost` | Hosts served the candidate portal |

- **Tests.**
  - `pnpm --filter @hirevion/recruitment-platform test` runs the unit and component tests.
  - `pnpm --filter @hirevion/recruitment-platform e2e` builds the app, serves it on port 3100 and runs Playwright:
    - every route for every role;
    - axe in both themes;
    - keyboard paths, CSP and the host split.
  - Run `pnpm --filter @hirevion/recruitment-platform exec playwright install chromium` once first.
  - A failed run leaves `recruitment-platform/playwright-report/`; open it with `pnpm exec playwright show-report`.
- **Adding a page.** Add an entry to `src/auth/manifest.ts` (path, permission, title key, owner)
  and a `page.tsx` under `src/app/recruiter/(shell)/` that calls `guardedPage` or `requireRoute`
  with that path. Add its title to both message catalogues. The tests fail until all three agree.

## Sign in locally

How accounts, sessions and the sign-in lookups work is in
[ADR-0013](../architecture/adr/0013-sign-in-and-sessions.md).

1. **Accounts.** `uv run hv migrate`, then `uv run hv seed-identity`. It creates, if missing:
   - the organisation "Acme Talent (dev)", with one user per role: `org-admin@acme.example.test`,
     `recruiter@acme.example.test`, `hiring-manager@acme.example.test` and
     `interviewer@acme.example.test`;
   - the super admin `super@hirevion.example.test` in the Platform organisation;
   - the department "Engineering" and its team "Platform hiring", with the recruiter in it.

   They all use `HV_SEED_PASSWORD` from `.env` (`hv env-sync` generates it). The command refuses
   to run when `HV_ENVIRONMENT=production`.
2. **Run it.** `uv run hv api` and the web app's `pnpm dev`, then sign in at
   `https://app.hirevion.localhost/login`. Through Caddy the session cookie is same-origin; in
   `next dev` without Caddy, `/api/*` is forwarded to `HV_API_INTERNAL_URL`.
3. **Email.** Reset, set-password and confirm-email links go to Mailpit
   (`https://mail.hirevion.localhost`). `hv api` sends them itself; with `HV_API_RUN_WORKERS=false`
   run `uv run hv worker` alongside it. A message that fails five times moves to the
   `hv:dead:mail` stream.
4. **Another super admin.** `uv run hv create-super-admin --email you@example.test --name "You"`
   prints a one-time set-password link, valid for 72 hours (`HV_SET_PASSWORD_TOKEN_HOURS`).
5. **Locked out.** Five wrong passwords (at sign-in or when confirming a change) lock the email
   for a minute, doubling up to an hour. `uv run hv reset-limits` clears every lockout and rate
   limit in the local Valkey (it refuses production). Locks are keys named
   `lockout:<SHA-256 of the lower-cased email>`, and limits are `hv:rl:<rule>:<subject>`.
6. **Breached-password check.** New passwords are checked against a bundled list and, with
   `HV_HIBP_ENABLED=true` (the default), the Have I Been Pwned range API. Only the first five
   characters of the password's SHA-1 leave the PC. Set it to `false` offline.

### Administration

How roles, guards, step-up and scope work is in
[ADR-0014](../architecture/adr/0014-organizations-and-access.md).

- **Organisation admins** (`org-admin@acme.example.test`) use Administration:
  - **Users:** invite people (they get a set-password email in Mailpit), change their roles,
    teams and access, disable or enable them.
  - **Roles:** custom roles, and the permission matrix.
  - **Teams and departments.**
  - **Organisation:** the profile.
- **Super admins** (`super@hirevion.example.test`) use Platform → Organisations to create,
  suspend and reactivate organisations. Super admins are users of the Platform organisation, so
  Administration → Users there invites another super admin.
- **Step-up:** role changes, invitations, enabling or disabling someone, custom-role changes and
  platform changes ask for the password again unless it was confirmed in the last
  `HV_STEP_UP_MINUTES` (10).
- **Development sessions** (the role picker under `next dev`) have no account behind them, so
  these pages show a notice asking you to sign in with a seeded user.
- **New API routes** must use `requires(...)` from `hirevion_api.authz` (or be listed in its
  `UNGUARDED` with a reason), and their guard must be added to the table in
  `backend/api/tests/test_authorization_matrix.py`. CI fails otherwise.

**End-to-end sign-in suite.** With the stack up, `hv seed-identity` done and `uv run hv api`
running:

```sh
HV_E2E_API=1 pnpm --filter @hirevion/recruitment-platform e2e
```

It builds the web app without development sessions and serves it on port 3101, behind a small
gateway on 3100 standing in for Caddy. It then works for real, reading the emails from Mailpit:
- signs in, resets passwords, changes email addresses and revokes sessions;
- invites users and confirms passwords;
- creates custom roles;
- disables users;
- creates and suspends organisations;
- creates a job, has its pasted description read, applies it and opens the job.

For the jobs test, start the API with the mock AI and its scripted answer, as CI does:

```sh
HV_AI_PROFILE=mock HV_AI_MOCK_SCRIPTS=recruitment-platform/e2e/auth/ai-scripts.json   HV_WEB_ORIGIN=http://app.hirevion.localhost:3100 uv run hv api --no-reload
```

Without them it reads the description with Gemini, which also passes but takes longer.

How it runs:
- It first clears local rate limits (`hv reset-limits`) and runs two browsers at a time, as CI
  does; more starve the API on a laptop.
- It invites its own super admins with `uv run hv create-super-admin`; set `HV_UV` to uv's full
  path if `uv` isn't on `PATH`.

### Jobs and job descriptions

How the pipeline works is in [ADR-0015](../architecture/adr/0015-jobs-and-documents.md).

- **Recruiters** (`recruiter@acme.example.test`) use Jobs:
  - **The list** filters by the status tabs and department, and searches titles or `JOB-0042`.
  - **New job** takes the fields and skills. Skills are suggested from the shared taxonomy;
    Enter adds one as typed.
  - **A job's page** has the status moves (Open, Pause, Resume, Close, Archive) and three tabs:
    Details, Description and History.
- **The description:**
  1. Paste it, or upload a PDF, DOCX or TXT file of up to 10 MB.
  2. The `documents` consumer reads it in the background: scan, text, sections, then one AI
     call (`jd.extract`) and an embedding. The tab shows each step.
  3. The review shows what was found, with the quote each skill came from, and how many items
     were left out because their quotes weren't in the text.
  4. "Apply to job" writes the reviewed fields as a new version.
- **Where it runs:** inside `uv run hv api` (`HV_API_RUN_WORKERS=true`), or alone with
  `uv run hv worker`. It uses the AI profile in `.env` (`HV_AI_PROFILE=dev` is Gemini).
- **ClamAV** (compose profile `core`) scans uploads on `127.0.0.1:3310`
  (`HV_CLAMAV_HOST`, `HV_CLAMAV_PORT`). Its first start downloads signatures for a few minutes.
  Until it's healthy, set `HV_DOCUMENTS_SCAN=false`; production refuses that setting.
- **When a description is stuck or failed:**
  - "Try again" on the Description tab re-queues a failed one.
  - Each failure has a reason: `unreadable`, `too-many-pages`, `no-text`, `ai-failed`,
    `budget-exceeded`, or `retries-exhausted` after five deliveries.
  - Events that gave up are in the `hv:dead:documents` stream
    (`docker compose exec valkey valkey-cli XRANGE hv:dead:documents - +`).
  - An infected file ends `quarantined`, and its blob moves under `<org>/quarantine/`.
- **Without blob storage** (`AZURE_STORAGE_*` unset), uploads answer 503
  `storage-unavailable`, and pasted descriptions still work.

### Resumes and candidates

- **On a job's Resumes tab:**
  - Pick or drop PDF, DOCX, TXT, JPG, PNG or TIFF files (10 MB each), or a ZIP of them (up to 50 MB and 200 entries).
  - Each file is sent in its own request, three at a time.
  - The list follows each resume through `scanning`, `extracting`, `ocr`, `parsing` and `parsed`, nesting an archive's entries under it.
  - Failed ones offer "Try again".
- **Candidates** appear on the job's Candidates tab and under Candidates.
  - A candidate's page shows every parsed item with "From the resume, page N", and their resumes and applications.
  - Flags (hidden text, injection attempts, possible duplicates, low OCR confidence) are shown as things to check.
- **Permissions:** uploading needs `candidates.manage` ("Upload resumes and manage candidates": org admins and recruiters); reading needs `candidates.view`.
- **Personal data:** Aadhaar numbers and virtual IDs, PANs, and passport, voter ID and bank account numbers written after their label, are masked to their last four characters before anything is stored or parsed. A scanned resume's page image still goes to the OCR service before masking (ADR-0015).
- **What the pipeline refuses or leaves out (D1 review):**
  - A Word file or PDF that inflates past its limit (64 MB for a Word file, 256 MB of PDF streams) is refused as `archive-bomb`; in a ZIP, an entry compressed more than 100 to 1 is skipped (`compressed-like-a-bomb`) and the rest is read.
  - Text drawn invisibly, painted over by a white shape, white on white, tiny, off the page, or hidden in Word (including in hyperlinks and styles) is left out and reported. White text on a dark banner or shaded cell is visible and stays.
  - Invisible characters (zero-width, bidi, Unicode tag characters, variation selectors) are removed and counted.
  - Plain instructions to the screener ("ignore all previous instructions", "rank me first") are replaced with a marker before the AI reads the resume, and the candidate shows the flag "Instructions to the screener were removed".
  - A quote counts as evidence only if it is long enough and is about what it supports (a skill's quote must mention the skill or one of its spellings).
  - A resume downloads only once it has been scanned; a ZIP itself never downloads (its entries do).
- **The synthetic set and the F1 evaluation:**
  - `uv run hv synth-resumes` writes 200 made-up resumes and `truth.jsonl` to `tools/devcli/.cache/resumes`.
  - `uv run hv eval-resumes` runs them through the pipeline in an organisation of its own, scores 14 fields, checks the exit criteria and writes `docs/evals/2026-10-resume-parse.md`. It uses the AI profile in `.env`; with `HV_AI_PROFILE=mock`, only the exit criteria mean anything.
  - The anti-virus test file is uploaded from memory, because Windows Defender removes it from disk.
- **The end-to-end suite** uploads a resume too: keep Azurite up (it is in the `core` profile).

### Screening and ranking

How it works is in [ADR-0016](../architecture/adr/0016-screening-and-ranking.md).

- **A job's Screening tab** sets the weights (they must add up to 100), the knock-out flags and blind mode. A job inherits the organisation's defaults (Administration → Organisation → Screening defaults) until it saves its own; "Use the default settings" goes back.
- **A job's Ranking tab:**
  - "Screen candidates" queues every candidate; the `screening` consumer in `hv api` (or `hv worker`) assesses each with the AI, and the tab shows progress.
  - "Screen again" after changing settings re-screens; unchanged candidates reuse their results without an AI call.
  - Click a name to see each factor's score and the resume quotes behind it, strengths, concerns and missing requirements.
  - Select candidates to shortlist, hold, mark for review or reject in bulk. Rejections, and decisions against the ranking, ask for a reason.
  - "Download CSV/Excel" asks for your password if you haven't confirmed it in the last few minutes.
- **Blind screening** is on by default and shown on the Ranking tab. Only an organisation administrator (`admin.organization.manage`) can turn it off for a job or for the organisation; a job's Screening tab warns when it is off, and results made without it are marked "Names shown". Blind mode removes names, contact details, links and handles, addresses, and lines about gender, age, marital status, religion, caste, nationality and the like (`hirevion_core.screening.blind`); a new way of writing one of these is a new rule and a new test.
- **Permissions:** `candidates.view` reads; `candidates.manage` screens and acts; `jobs.create` edits a job's settings; `admin.organization.manage` edits the defaults.
- **Candidates whose screening failed** five times go to "Marked for review" with the reason in their history, and the job's ranking carries on without them. "Screen again" tries them afresh.
- **Evaluating the ranking:** `uv run hv eval-screening` after `hv eval-resumes` (see `docs/evals/2026-10-screening.md`).

### Question library and interview templates

How it works is in [ADR-0017](../architecture/adr/0017-interview-configuration.md).

- **Question library (`/questions`):**
  - The tabs are the categories. Filter by status, type and difficulty, or search the text and topic.
  - "New question" saves it approved, or as a draft. Every later save is a new version, listed at the bottom of the question.
  - Only approved questions can be pinned to templates. Archived ones are hidden until you filter for them; restoring one makes it a draft again.
- **Generate with AI:**
  - Choose the skills, how many, the level, and optionally a job, a candidate and a template. The library's questions for those skills go along so the AI avoids repeats.
  - The results arrive as drafts marked "AI draft". Open each one, edit it if needed, and approve it.
  - The API makes the call with the AI profile in `.env`. With `HV_AI_PROFILE=mock`, `HV_AI_MOCK_SCRIPTS` supplies the answer (the end-to-end suite uses `recruitment-platform/e2e/auth/ai-scripts.json`).
  - Without working AI keys, generation answers "AI unavailable"; everything else works.
- **Templates (`/interviews/templates`):**
  - A new template starts from the organisation's interview defaults (Administration → Organisation → Interview defaults).
  - Skill weights, the difficulty mix and the rubric must each add up to 100.
  - The skill matrix under the form shows how many questions each skill gets at each difficulty, against the approved library questions available; "short" means the interview will write the rest.
  - Saving an existing template creates the next version. The Versions tab lists them all, and interviews keep the version they were scheduled with. Archive a template to stop new interviews using it.
- **Permissions:**
  - `questions.view` and `questions.manage` for the library;
  - `interviews.templates.view` and `interviews.templates.manage` for templates;
  - `admin.organization.manage` to change the defaults.

### Interviews and invitations

How it works is in [ADR-0020](../architecture/adr/0020-interviews-and-invitations.md).

- **Creating interviews:** on a job's Ranking tab (the job must be open), select candidates, then "Create interview". Choose a template (or the job's own, set on the job's Details tab), the window, and whether to invite now. Candidates who can't have one (no email, already invited, rejected) are listed with the reason; the rest are created.
- **The invitation** goes through the outbox and the mail consumer to Mailpit (http://127.0.0.1:8025). It holds PRD §25's eight contents and, for a new candidate, a set-password link to the candidate portal (`HV_CANDIDATE_ORIGIN`, valid `HV_CANDIDATE_LINK_HOURS`). Set the organisation's support email under Administration → Organisation.
- **`/interviews`:** Upcoming (scheduled and invited), Live (in progress and interrupted) and Completed (everything that's over). An interview's page shows the pinned template version and policy, the window, the reviewers, the history and every email sent, and lets `interviews.manage` holders send or resend the invitation, reschedule, cancel (with a reason the candidate sees) and change reviewers.
- **Reminders and expiry:** the scheduler in `hv api` (or `hv worker`) runs every minute. To try it, move a window with SQL (`UPDATE interviews SET expires_at = now() - interval '1 minute' WHERE ...`) and watch the interview become Expired within a minute.
- **The dashboard** shows the ten PRD section 10 figures under its seven filters (date range, recruiter, team, job, department, interview status, candidate status):
  - Open jobs; active candidates (people with an application still undecided); candidates screened; candidates shortlisted; applications in the hiring pipeline.
  - Interviews scheduled, live and completed; pending reviews (finished interviews waiting for a decision); proctoring alerts (warnings and critical events nobody has reviewed yet).
  - The date range applies to the date of the thing counted (job created, application created, interview window start). A figure the signed-in user may not read shows "no data yet". The job and candidate figures cover the jobs the user reaches, including those they are hiring manager of; the interview figures cover the interviews they can open (the Interviews page's scope).
  - If the figures fail to load the page says so, with a retry, instead of showing zeros.
- **Permissions:** `interviews.view` reads (interviewers see only interviews they review); `interviews.manage` changes.

### Candidate desktop sign-in and releases

How it works is in [ADR-0021](../architecture/adr/0021-candidate-desktop-auth.md); the wire format is `docs/api/contracts/candidate-auth.md`.

- **Signing key:** `HV_CANDIDATE_TOKEN_KEY` in `.env` (`uv run hv env-sync` adds one). Without it the API makes one at start-up, and every candidate is signed out when it restarts.
- **A candidate who can sign in** needs an active account (they set a password from the invitation email; SP-07b's portal) and an interview they were invited to, in an open job, inside its window.
- **New devices:** with Administration → Organisation → "Ask for an emailed code on a new computer" on (the default), a device's first sign-in sends a 6-digit code to Mailpit instead of signing in.
- **Releases (`/platform/desktop-releases`, super admins):** set each channel's oldest allowed version (older apps get `426` at sign-in) and its download address; add builds as drafts with their update bundle's URL and minisign signature, then publish them. A rollout below 100% reaches that share of devices, the same ones each time.
- **Trying the API by hand:** every request needs a DPoP proof signed by a P-256 key (see `backend/api/tests/test_candidate_auth_api.py`'s `Desktop` class for a complete client).
- **Stuck candidate:** `uv run hv reset-limits` clears lockouts; a reused refresh token revokes the device's sign-in (they sign in again).

### Candidate portal

How it works is in [ADR-0022](../architecture/adr/0022-candidate-portal.md).

- **Where:** https://candidate.hirevion.localhost through Caddy (only `/api/v1/portal/*` reaches the API from that host), or http://candidate.hirevion.localhost:3000 under `next dev`. The API accepts the portal's cookies only from `HV_API_PORTAL_ORIGINS` (default: those two and the end-to-end server's `:3100`).
- **Accepting an invitation:** open the `/invitation/<token>` link from the invitation in Mailpit, choose a password of 12 or more characters, then sign in. The same password works in the desktop app. "Forgot your password?" sends a reset link to an active account and a fresh invitation link to one that never set a password.
- **Pages:** Interviews (windows in the interview's time zone, a countdown on the server's clock), Download (the stable channel's download address and newest release from `/platform/desktop-releases`, with system requirements and install help), Notices (§83's disclosures and `docs/policies/`, or `HV_POLICIES_DIR`), Report (a placeholder until SP-17) and Requests.
- **Requests:** each is acknowledged by email (`RQ-` reference) and listed for recruiters at Candidates → Requests (`/candidates/requests`), where `candidates.requests.manage` holders set in progress, resolved or declined with a reply the candidate sees. Adjustments asked for before the interview also appear on the interview's Accommodations card, where they're decided.
- **End to end:** `e2e/auth/portal.spec.ts` runs with the sign-in suite, against the same API (it opens the emailed links' paths on the portal's `:3100` host). On a busy PC, give that API its own database (`POSTGRES_DB=<name> uv run hv migrate`, then `hv seed-identity` and `hv api` with the same variable).
- **Stuck candidate:** `uv run hv reset-limits` clears the shared portal and desktop lockout.

### The interview (engine, agent and simulator)

How it works is in [ADR-0030](../architecture/adr/0030-interview-engine.md); the desktop's wire format is `docs/api/contracts/interview-session.md`.

- **A whole interview without the desktop:** `uv run hv seed-identity` once, `uv run hv api` running, then `uv run hv interview-sim --persona strong`.
  - The personas are `strong`, `partial`, `weak`, `silent`, `adversarial` and `cheating`.
  - It seeds a synthetic job, candidate and question library in the development organisation, approves typed answers, signs in like the desktop app (DPoP) and answers every question.
  - The last line is the interview's page, with the transcript, each question's source and the skills' coverage.
- **Without LiveKit running,** start the API with `HV_MEDIA_BACKEND=fake` (never in production): rooms and tokens are faked, and text-mode interviews run fully. Voice interviews need `uv run hv up --media` and the agent.
- **The AI interviewer (voice):**
  1. `uv run python -m hirevion_interview_agent.agent download-files` once.
  2. `uv run python -m hirevion_interview_agent.agent dev` with `hv up --media`.

  The API dispatches it to an interview's room on `start` (`HV_AGENT_NAME`, default `hirevion-interviewer`); it never joins rooms on its own. LiveKit's webhooks reach the API at `http://host.docker.internal:8000/api/v1/livekit/webhook` (set in `compose.yaml`).
- **What candidates are told:** Administration → Organisation → Interview briefing holds the instructions (empty uses the standard ones) and the FAQ. The AI answers candidates' final questions only from that FAQ, and passes anything else on.
- **Accommodations:** a candidate's requests show on the interview's page. Approving "Typed answers" switches the interview to text mode before it starts; decisions can't change once it has started.
- **Interruptions:** when the candidate leaves the room the interview is Interrupted and its clock stops. Coming back within the grace (300 s; doubled with "Breaks") resumes it with a recap, up to three times; after the grace the scheduler marks it Abandoned and the candidate goes back to the shortlist.
- **A crashed agent:** kill the agent process mid-interview. LiveKit's webhook makes the API dispatch another, which waits for the old one's lock (under 10 s), apologises and asks the open question again.
- **Watching live:** an interview's page follows `/api/v1/ws/interviews/{id}` while it runs. To see the raw events, run `XRANGE hv:rt:interview:<id> - +` in `valkey-cli`.
- **Transcript files** (JSON, VTT, TXT) are written to blob storage when the interview ends, by the worker in `hv api` (or `hv worker`), and linked from the interview's page.
- **Tuning prompts:** `backend/core/src/hirevion_core/engine/prompts/` holds the analysis and follow-up prompts; a change gets a new version name (SP-10's eval harness gates it).

### Evaluation and AI governance (SP-10)

How it works is in [ADR-0031](../architecture/adr/0031-evaluation-and-governance.md); the plan is `docs/superpowers/plans/2026-10-10-sp-10-evaluation.md`.

- **What happens when an interview ends:** completing it queues an `evaluation` event in the same transaction. The worker (in `hv api`, or `hv worker`) moves the interview to Evaluating, makes one strong-model call per answered question and one for the summary, then writes the evaluation, moves it to Evaluated and queues the `evaluation.completed` webhook event. The interview's page shows it under Evaluation.
- **When it doesn't finish:** the run is retried (five attempts, a minute apart). If the model is down or the organisation's AI budget is spent, the interview goes back to Completed and the page says the evaluation couldn't be completed. An organisation admin (`admin.ai.manage`) presses Retry the evaluation once the cause is fixed.
- **Where the audit trail is:**
  - `evaluations` holds the pinned versions (prompt, rubric weights, evaluation version, models) and the result; `question_evaluations` holds the eight scores with their quotes.
  - `ai_invocations` holds every call: model name and version, prompt, rubric and evaluation versions, timestamp, the input references (find a run's calls with `input_refs->>'evaluation' = '<id>'`) and the output.
  - Each interview's history shows `evaluation_started` and `evaluated`, and the organisation's audit log records re-runs and reviewers' scores.
- **Repeating an evaluation with its pinned versions:** `uv run hv eval-rerun <interview-id>`, or Repeat with pinned versions on the interview's page (organisation admins). It loads the prompt, rubric weights and skill plan the evaluation recorded, evaluates again and prints how far each score moved; the interview's own evaluation is not changed. Tolerance is 1.0 per dimension and 0.5 per question and overall (`--dimension`, `--overall`). The command exits 1 outside it; the report also says when the transcript or the model differs from the original, because then a difference says nothing about the prompt.
- **Changing a prompt or the rubric:**
  1. Add a new file (`evaluation/prompts/evaluation-question-v2.md`, `evaluation/rubrics/dimensions-v2.md`); never edit one in use.
  2. `uv run hv eval-interviews --prompt-version evaluation-question-v2` runs the labelled set (`evaluation/eval_set/cases.json`, from the simulator's personas) through it and applies the gate: thresholds, no fall from the committed baseline, and the prompt's required clauses. It exits 1 when blocked. Add `--live` to use the configured vendor instead of the mock (needs a working key), `--report docs/evals/2026-10-interviews.md` to write the results.
  3. When it passes, point `ACTIVE_QUESTION_PROMPT` (or the rubric or synthesis prompt) at the new name in `evaluation/registry.py`, bump `EVALUATION_VERSION` if the arithmetic changed, and run `uv run hv eval-interviews --update-baseline`. CI runs `hv eval-interviews` on every backend change, so an unrecorded change fails there.
  4. If the personas change, regenerate the set with `hirevion_interview_simulator.eval_set.write` (a test checks it).
- **Reviewers' calibration:** on a finished interview's page, open a question, score the eight dimensions yourself and save; the AI's scores and their quotes appear beside yours. Organisation admins and recruiters (`reports.analytics.view`) see the organisation's weighted kappa, Spearman, mean gap and the AI's bias under the interview's evaluation.
- **Database tests while other lanes test:** the test database and Valkey database 15 are shared, so run with your own database (`CREATE DATABASE hirevion_test_c4`, then `HV_TEST_DATABASE=hirevion_test_c4 uv run pytest ...`) to avoid another session rebuilding the schema under you.

### Proctoring (engine and live view)

How it works is in [ADR-0032](../architecture/adr/0032-proctoring-engine.md); the desktop's wire format is `docs/api/contracts/proctoring.md`.

- **Run it:** the proctoring watcher and the `recording.gap` consumer run with the other workers (`hv api`, or `hv worker`). Without them events are still stored and alerted, but missed heartbeats, a camera LiveKit saw go down and recording gaps are not turned into events.
- **Feed it without the desktop:** the interview simulator's `DesktopClient` signs in like the app; after `start`, `POST /proctoring/session` and then `/events` and `/heartbeat` with its session token (see `backend/api/tests/test_proctoring_api.py` for every call).
- **What a level turns on:** `off` stores nothing; `basic` face and focus; `standard` adds gaze, phone, processes and displays; `strict` adds audio and the third eye, and treats a second display as CRITICAL. A template's level is copied into each interview, and the session pins the full policy when it opens, so changing a template never changes a running interview.
- **Severities** are the master plan's §6.12 table (`hirevion_core.proctoring.rules`). To see why an event got its severity, read `details.server.reasons` on the event (for example `duration:31000ms`, `category:remote_access`, `repeated:5 in 600s`). A device's `severity_hint` is only a note.
- **Application rules:** the platform catalogue is in `app_categories` and `app_rules` (organisation_id empty). A blocking `name` rule needs a `with` condition; the database refuses one without. Publisher names are the signer's certificate subject and are matched exactly: check them on a Windows machine with `Get-AuthenticodeSignature`. The catalogue is read-only to the API; SP-22 adds its editor.
- **Watching live:**
  - The interview page shows the monitoring panel to anyone with `reports.proctoring.view` and `interviews.view`; the panel starts from `GET /api/v1/proctoring/{id}/live` and follows `/api/v1/ws/proctoring/{id}?after=<last id>`.
  - To see the raw events, run `XRANGE hv:rt:interview:<id> - +` in `valkey-cli`: `PROCTOR_EVENT`, `PROCTOR_STATUS` and `PROCTOR_REVIEW` are there next to the interview's own events.
  - `POST /api/v1/proctoring/{id}/observe` gives a hidden, subscribe-only LiveKit token (audited).
- **Reviewing:** an event can be confirmed, marked a false positive or not relevant with a reason (`interviews.manage` and `reports.proctoring.view`). It stays in the report and is audited (`proctoring.event_reviewed`).
- **Nudges:** `policy.nudges` (in the pinned policy) says which events nudge the candidate, from which severity, how often and how many. They are in the interview's hot copy (`GET /session`'s `notice`) and in `hv:iv:<id>:nudges`, which the agent turns into `hv.state`.
- **Snapshots:** a CRITICAL event records requests (`proctor_evidence` rows with no blob and `ref.status` `requested`); the desktop gets them in the heartbeat answer and answers within two minutes. Unanswered ones stay visible in the evidence list.
- **Measuring the latency:** `uv run pytest backend/api/tests/test_proctoring_api.py -k 95th -s` prints the median, p95 and maximum from the desktop's POST to the dashboard's websocket.
- **Tests on a busy PC:** several test runs at once share the test database and Valkey database 15. Set `HV_TEST_DATABASE=<your own database>` (create it once) and `HV_TEST_VALKEY_DB=<0-14>` to keep a run to yourself.

### Reports, review and Candidate 360 (SP-17)

How it works is in [ADR-0023](../architecture/adr/0023-reports-review-and-hiring-workflow.md).

- **PDFs need Chromium on the API's side.** Run `uv run playwright install chromium` once (the Python package is pinned to the same Playwright version as the web suite, so the browsers installed for end-to-end tests serve both). Without it the web views work and an export answers `503 pdf-unavailable`; the report tests that render a PDF skip with that hint.
- **Where things are:**
  - Reports: `/reports/interview/<interview id>`, `/reports/proctoring/<id>`, `/reports/coding/<id>`; the internal candidate report is the Reports tab of Candidate 360; the candidate-visible one is the "What the candidate sees" card of the review workspace.
  - The review workspace is `/interviews/<id>/review`, the pending-review queue `/reports/pending` (also the Reports page's "Pending review" tab and the dashboard's count).
  - Candidate 360 is `/candidates/<id>`, thirteen tabs; a tab the reader's role may not see is left out.
- **What the candidate sees:** an organisation admin picks which of the five items may ever be shown (Administration, Organisation, "Candidate report"; completion and next step are on by default). A recruiter edits the draft, then "Approve and release"; the portal's `/report` shows only that frozen release and a PDF of it. "Withdraw" hides it again. Nothing internal (scores, flags, proctoring, notes, hiring-manager input) can be put in a release.
- **The hiring status** is on the review workspace and, per application, on Candidate 360 and the pipeline board's card menu. `interview_invited`, `interview_started` and `interview_completed` follow the interview and cannot be chosen. `selected`, and a rejection after an interview, are the final decision: they need `hiring.decide` (organisation admins and recruiters) and a reason. Hiring managers recommend with `hiring.input`; that never moves a status.
- **Playing recordings:** the workspace asks for five-minute read links to each assembled track and audits every play (`recording.viewed`). Assembly needs `ffmpeg`; without it (a plain Windows dev machine) the tiles say "Not ready yet (assembly-pending)" and the transcript, events, scores and notes still work.
- **Feed it without the desktop:** `uv run hv interview-sim --persona partial` now also opens a proctor session, sends one scripted event for each event section of the proctoring report, a heartbeat and camera, microphone and screen segments (`--no-telemetry` for the old behaviour). `--password <text>` sets the candidate's portal password, and the run prints `candidate_email=` beside `interview_id=`.
- **Reading the audit log:** `uv run hv audit-tail [--action report.viewed] [--resource <id>] [--limit 50] [--json]`. Report, recording, score, note, hiring and release actions are listed in ADR-0023; a reviewed proctoring event is recorded against the event, with the interview in its details.
- **The golden path (Playwright, needs the stack and the real API):** create a database (`CREATE DATABASE hirevion_e2e_<you>`), then with `POSTGRES_DB=hirevion_e2e_<you>`, `HV_AI_PROFILE=mock`, `HV_AI_MOCK_SCRIPTS=recruitment-platform/e2e/auth/ai-scripts.json`, `HV_WEB_ORIGIN=http://app.hirevion.localhost:3100`, `HV_MEDIA_BACKEND=fake` and `HV_HIBP_ENABLED=false` start `uv run hv api --no-reload`, and run `pnpm --filter @hirevion/recruitment-platform exec playwright test e2e/auth/golden-path.spec.ts --workers=1` with `HV_E2E_API=1`. It takes about a minute and a half.
- **Tests on a busy PC:** the same as for proctoring: your own `HV_TEST_DATABASE` and `HV_TEST_VALKEY_DB`.

## Desktop app (`ai-interviewer-desktop`)

The candidate app is Tauri 2: a React webview (`src/`) plus Rust (`src-tauri/`), which also
holds the native crates in `src-tauri/crates/`.

1. `pnpm install` once at the repo root.
2. `pnpm --filter @hirevion/ai-interviewer-desktop tauri dev` starts Vite on port 1420 and opens
   the app. Webview changes reload instantly; Rust changes rebuild the app. The first Rust build
   takes about six minutes.
3. Before committing, run the checks CI runs: `pnpm lint`, `pnpm typecheck` and `pnpm test` at the
   repo root, then in `ai-interviewer-desktop/src-tauri`: `cargo fmt --all --check`,
   `cargo clippy --workspace --all-targets -- -D warnings` and `cargo test --workspace`.

`rust-toolchain.toml` pins the Rust version; rustup installs it automatically on first use.
`cargo deny check` (with `cargo-deny` installed) checks licences and advisories the way CI does.

### Sign-in and the system check (SP-08a)

How it works is in [ADR-0018](../architecture/adr/0018-desktop-device-keys-and-tokens.md).

- **The flow:** launch → version check → sign-in → (emailed code on a new device) → your interviews → system check → ready.
- **Where calls go:** the app calls the API from Rust, never from the webview, at `HV_API_URL` (default `https://api.hirevion.localhost/api/v1`, through Caddy). Debug builds read `HV_API_URL` at run time, so `HV_API_URL=http://127.0.0.1:8000/api/v1 pnpm tauri dev` talks to `uv run hv api` directly.
- **Before the candidate sign-in API exists (SP-07c),** `HV_DESKTOP_STUB=1` makes a debug build answer from canned data:
  - any email works with the password `stub`;
  - an email starting `new` asks for the code `123456`;
  - `HV_DESKTOP_STUB_NATIVE=1` also makes the native system checks (CPU, memory, disk, displays, privacy, Media Foundation, screen capture) pass without touching the machine; the end-to-end test sets it.
- **The device key** lives in the TPM when there's one (`Hirevion Device Key v1`). `cargo test -p hv-security -- --ignored` checks it on real hardware.
- **The refresh token** is DPAPI-encrypted in `%LOCALAPPDATA%\com.hirevion.interview\vault`. Signing out deletes it.
- **Integrity in release builds:** the app removes the `WEBVIEW2_*` variables that change the browser before it starts, and reports them.
- **Integrity in debug builds:** the app keeps them, so the fake-device spike runs below still work, and only reports them.

### Installers, updates and crash reports (SP-08c)

How it works is in [ADR-0019](../architecture/adr/0019-desktop-packaging-and-updates.md); the manifest's wire format is `docs/api/contracts/candidate-auth.md`, "Desktop releases".

**Build the installers**

- `pnpm --filter @hirevion/ai-interviewer-desktop bundle` makes the x64 installer; add `-- --target arm64` or `-- --target all` for ARM64. It prints each installer's size, SHA-256, Authenticode status and updater signature.
- The output is `ai-interviewer-desktop/src-tauri/target/<triple>/release/bundle/nsis/*-setup.exe`, with a `.sig` beside it.
- **ARM64** needs the Visual Studio Installer component "MSVC v143 – VS 2022 C++ ARM64 build tools"; the script adds the Rust target itself.
- **Build-time settings** (real environment, or the root `.env`):
  - `HV_API_URL`: the API root compiled into the app (`https://…/api/v1`).
  - `HV_GLITCHTIP_DSN`: crash reporting; leave it out and reporting is off.
  - `--no-updater` skips the update artifacts, so no updater key is needed.
- **Install without admin rights:** run the `-setup.exe`; it installs for the current user only. The default folder is `%LOCALAPPDATA%\Hirevion AI Interview`.
  - Checked with a non-elevated silent install (`/S /D=<folder>`): it wrote only that folder and `HKCU`, and `uninstall.exe /S` removed everything. The x64 installer is about 8 MiB.
  - Uninstall with the `uninstall.exe` in the install folder.
- **ARM64 in CI:** run the "Desktop installers" workflow by hand. It builds x64 and ARM64 without signing and keeps the installers as artifacts. It hasn't run on a runner yet; building ARM64 locally needs the Visual Studio ARM64 build tools.

**Sign**

- **Authenticode (development):** the script creates a self-signed certificate on demand in `Cert:\CurrentUser\My` ("Hirevion Dev Code Signing") and signs the app and installer with it. Windows doesn't trust it; it only proves the step works. It is never exported or committed. `HV_SIGN=0` skips signing.
- **Authenticode (production, later):** buy an OV code-signing certificate, then set `HV_SIGN_THUMBPRINT` to its thumbprint (it must be in your certificate store) and `HV_SIGN_TIMESTAMP_URL` to the CA's RFC 3161 timestamp server. SmartScreen reputation builds with downloads; an EV certificate no longer skips it.
- **Updates (development key):** the key pair lives outside the repo. To make one:
  - `pnpm --filter @hirevion/ai-interviewer-desktop exec tauri signer generate -w %USERPROFILE%\.hirevion\updater-dev.key`;
  - put the password in the root `.env` as `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`;
  - paste the printed public key into `plugins.updater.pubkey` in `src-tauri/tauri.conf.json` (the committed key matches the author's development key, so a new one means a new key pair and an app rebuilt with it).
- The bundle script uses `%USERPROFILE%\.hirevion\updater-dev.key` unless `TAURI_SIGNING_PRIVATE_KEY` says otherwise.
- **Where the private material lives (never in the repo):**
  - the updater key is `%USERPROFILE%\.hirevion\updater-dev.key`, and its password is `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` in the root `.env`;
  - the Authenticode certificate is in your Windows certificate store (`Cert:\CurrentUser\My`, subject "Hirevion Dev Code Signing") and is never exported;
  - the downloaded `msedgedriver` is under `%USERPROFILE%\.hirevion\msedgedriver`.
  - Lose the development key and you make a new pair, paste its public key into `tauri.conf.json` and rebuild; installs made with the old key can no longer update.

**Publish a development release**

1. Raise the version in **both** `src-tauri/tauri.conf.json` and the workspace `version` in `src-tauri/Cargo.toml` (a test checks they match), then run `bundle`.
2. Put the `-setup.exe` on an `https://` address the candidate's PC trusts. The server only accepts https URLs, and release builds refuse anything else.
3. As a super admin (with a recent password, because registry changes need step-up), call the registry:
   - `POST /api/v1/platform/desktop-releases` with `{"version": "0.2.0", "channel": "stable", "arch": "x64", "url": "https://…/…-setup.exe", "signature": "<the whole text of the .sig file>", "notes": "…", "rollout_percent": 100}` registers a draft;
   - `PATCH /api/v1/platform/desktop-releases/{id}` with `{"status": "published"}` offers it. A lower `rollout_percent` offers it to that share of devices.
   - `backend/api/tests/test_candidate_auth_api.py` shows complete requests.
4. To force the update gate, raise the channel's `minimum_version` above the installed version (`PUT /api/v1/platform/desktop-channels/stable`). The installed app then stops at "Update required"; **Update now** downloads, verifies and installs the published release, and the new version starts by itself.
5. A downgrade is refused by the app even if the server offers one (`cargo test -p hirevion-desktop --test updater`).

**Crash reports**

- Build with `HV_GLITCHTIP_DSN=https://<key>@<glitchtip host>/<project>` and Rust panics and webview errors arrive in GlitchTip. Nothing identifying is sent: emails, tokens, profile paths, addresses and the computer's name are removed first (`cargo test -p hirevion-desktop crash::`).
- Without the setting the build reports nothing.

**End-to-end test**

- `pnpm --filter @hirevion/ai-interviewer-desktop e2e` builds the debug app (`-- --skip-build` reuses it), starts `tauri-driver` and walks launch → sign in → interviews → briefing → system check → consent → ready on the stub backend with fake camera and microphone. It opens the app window for a minute.
- One-time setup: `cargo install tauri-driver --version 2.1.0 --locked`. The matching `msedgedriver` is downloaded to `%USERPROFILE%\.hirevion\msedgedriver\<version>` on first use (or set `MSEDGEDRIVER`).
- If it fails, `ai-interviewer-desktop/e2e/output/failure.png` shows where it stopped. CI runs the same thing as the `desktop-e2e` job.

### Unattended spike runs

Debug builds can run a spike page by themselves and write a JSON report (including the CPU
use of the app and all its WebView2 processes) to `ai-interviewer-desktop/spike-results/`. From
`ai-interviewer-desktop`, in Git Bash:

```
HV_SPIKE=media:45:faces=gpu WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--use-fake-device-for-media-stream pnpm tauri dev
```

`faces` can be `gpu`, `cpu` or `off`. The fake-device flag feeds a synthetic camera and tone
instead of your webcam and microphone; leave it out to test with the real devices. The app
closes itself when the report is written.

### Screen-capture benchmark

`crates/recorder/examples/capture_bench.rs` records every display into 10-second H.264 MP4
segments and reports CPU, bytes per minute and timings. Run it from
`ai-interviewer-desktop/src-tauri`:

```
cargo run --release -p hv-recorder --example capture_bench -- --seconds 60 --out ..\spike-results\capture
```

The defaults are the ADR-0006 settings: constant quality 50 and one keyframe per segment. Add
`--vbr --bitrate 1500000` to compare with a variable bit rate, `--software` to force the
software encoder, `--primary-only` for one display, and see the file header for the rest.
Segments go to `display-<n>/<seq>.mp4`, with a `manifest.jsonl` (frames, bytes, SHA-256) next
to them. `spike-results/` is gitignored because the recordings show your screen; delete the
videos when you're done.

For numbers you can compare between runs, put the same thing on screen each time:
`examples/activity.html` simulates a coding interview (`?static=1` for a still screen). Open it
in a separate Edge guest window, which never signs in or syncs, and don't use the PC during
the run:

```
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --user-data-dir=%TEMP%\edge-bench --guest --start-maximized --app=file:///D:/Deva/Hirevion/ai-interviewer-desktop/src-tauri/crates/recorder/examples/activity.html
```

The ignored hardware test records three seconds of the primary display:
`cargo test -p hv-recorder --test capture_smoke -- --ignored`.

## Testing the third-eye camera from a phone

Phone browsers only allow the camera on HTTPS pages and can't use Caddy's local certificate,
so the page goes through a Cloudflare quick tunnel, while the video itself stays on your Wi-Fi
(ADR-0008).

1. Once: `winget install --id Cloudflare.cloudflared`, then open a new terminal.
2. Put the phone on the same Wi-Fi as this PC.
3. Set `LIVEKIT_NODE_IP` in `.env` to this PC's LAN address, then run `uv run hv up`.
   `hv eye-tunnel` tells you the address it detects if the setting is still `127.0.0.1`.
4. In one terminal, from `third-eye`: `pnpm dev`. The page is also at
   `https://eye.hirevion.localhost` on this PC.
5. In another terminal: `uv run hv eye-tunnel`. Scan the QR code with the phone, or open the
   printed link, and tap **Start camera**.
6. To watch the phone from the desktop app:
   - Run `uv run hv lk-token --room spike --identity desktop --copy`.
   - Open the app's **LiveKit spike** page, paste the token, and click **Join**.
   - The page shows the connection type (UDP or TCP, direct or relayed), round-trip time,
     resolution, frame rate and bit rate.

### Real pairing through the API (SP-13)

The desktop asks the API for a pairing and shows its QR code; the phone redeems it once.

1. Steps 1–4 above, plus the API (`uv run hv api`, with `HV_MEDIA_BACKEND` unset so it uses
   LiveKit) and the workers (`uv run hv worker`, which also collect Egress files).
2. `uv run hv eye-tunnel --page-only` prints `HV_THIRD_EYE_URL=https://….trycloudflare.com`. Put
   that line in `.env` and restart the API: QR codes now point at the tunnel. The tunnel's Caddy
   site passes only `/api/v1/third-eye/redeem` and `/rejoin` to the API, and `/rtc` to LiveKit.
3. Pair from the desktop (B4's pairing screen), or by hand: `POST /api/v1/third-eye/pairings`
   with the interview-session token, then open `qr_url` on the phone.
4. Check: the desktop's `GET /third-eye/pairings/{id}` goes `issued` → `redeemed` →
   `connected`; locking the phone makes it `disconnected` within a couple of seconds and, once an
   interview is running, raises `THIRD_EYE_DISCONNECTED` on the live dashboard within 10 s.
   Pairing again shows `revoked` for the old pairing and the old phone's page stops.
5. On this PC only (no tunnel), `https://eye.hirevion.localhost/#t=<token>` works too.

**Measuring pairing without a phone:** from `third-eye`, `pnpm e2e` runs headless Chromium with a
fake 720p camera against the local LiveKit and prints "Paired in N s" (about 1.6 s on this PC;
the budget is 60 s). Real phones (iOS Safari 16.4+, Android Chrome) remain a hands-on check.

**Egress:** `uv run hv up` starts `egress` with the `media` profile (the first pull is about
1 GB). It writes into `infrastructure/local/egress/` (gitignored), and the media worker moves
each file into blob storage under `{org}/interviews/{id}/audio/` or `third-eye/`; playback then
lists `conversation-audio-N` and `third-eye-N`. `HV_EGRESS_OUTPUT=off` turns it off;
`HV_EGRESS_LOCAL_DIR` moves the shared directory.

Press Ctrl+C in the `eye-tunnel` terminal as soon as you're done: while it runs, the page and
LiveKit signalling are reachable at a public (random) address. Docker Desktop's installer already
allows its backend through Windows Firewall. If the phone connects but shows no video, check the
firewall allows UDP 7882 and TCP 7881 for "Docker Desktop Backend".

## Quality gates (D1)

CI and `bash scripts/ci-local.sh` run the same gates; the local script is the merge gate while
GitHub Actions are off. Every scanner is run by `scripts/gates.sh`, which both call, so the two cannot
drift. Nothing needs admin rights: the scanners are pinned Docker images (Docker Desktop is already
required), and Bandit, `pytest-cov` and `pip-licenses` come with `uv sync`.

| Gate | Where it runs | Run it alone | A finding fails when | Read it |
|---|---|---|---|---|
| Python coverage | `python` job | `uv run pytest --cov` | the domain code is under 85% | below |
| Web coverage | `js` job | `pnpm --filter @hirevion/recruitment-platform test:coverage` | a figure falls under `thresholds` in `vitest.config.ts` | the printed summary |
| Bandit | `python` job | `bash scripts/gates.sh bandit` | medium severity or worse | each issue names its rule (B6xx) |
| Semgrep | `semgrep` job | `bash scripts/gates.sh semgrep` (about 7 minutes) | any finding of `p/python`, `p/typescript`, `p/react`, `p/secrets`, `p/owasp-top-ten` | each finding names its rule |
| osv-scanner | `dependencies` job | `bash scripts/gates.sh osv` | a known vulnerability in `uv.lock`, `pnpm-lock.yaml` or `Cargo.lock` | the table lists the fixed version |
| Licences | `dependencies` job | `uv run hv licenses` (`--python` or `--js`) | a licence outside master plan section 13 | each line is `package version: licence` |
| Trivy | `compose` job | `bash scripts/gates.sh trivy hirevion-api:ci-local` | HIGH or CRITICAL with a fix available, in the API image | the table lists package and fixed version |
| SBOM | `compose` job | `bash scripts/gates.sh syft hirevion-api:ci-local` | the scan can't run | `.ci-local/sbom.spdx.json` (CI uploads it as `api-image-sbom`) |

- **Python coverage.**
  - *Domain code* means `hirevion_core`: identity and access, jobs, documents, candidates, screening, interviews, the engine, evaluation, proctoring, recordings, reports.
  - Not measured, because they are exercised end to end or by contract tests against fakes: the API's routes, the tools and the interview agent, and the vendor and I/O adapters listed under `omit` in `pyproject.toml` (the OpenAI-compatible and Deepgram clients, blob storage, SMTP, ClamAV, OpenTelemetry, the migration runner, ffmpeg).
  - `uv run pytest --cov --cov-report=term-missing` lists the lines that no test reaches.
  - The tests need the stack (`uv run hv up`), as without coverage.
- **Web coverage** is V8's, over `recruitment-platform/src`. The floors in `vitest.config.ts` are what was measured on 2026-10-22, rounded down: raise them when coverage rises, never lower them to pass.
- **Accepting a finding.** Fix it first. If it is a false positive or a deliberate choice, say why beside the code, in the scanner's own form:
  - Bandit: `# nosec B608` (the rule id) and a comment line above saying why.
  - Semgrep: `# nosemgrep: <rule id>` on the line before the finding, with the reason in the line above that.
  - Ruff: `# noqa: S608`, as before.
  - osv-scanner: an `[[IgnoredVulns]]` entry in `osv-scanner.toml` with a `reason` and an `ignoreUntil` date (about six months out), so it comes back for a second look.
  - Licences: an `EXCEPTIONS` entry in `tools/devcli/src/hirevion_devcli/licenses.py` with its reason.
- **Semgrep's file list** is `.semgrepignore` (dependencies, build output, tests, generated code). The gate mounts the source directories one by one, not the repository: a git worktree's `.git` points outside the container, and Semgrep then walked `node_modules` for 39 minutes.
- **Updating a scanner.** The versions are at the top of `scripts/gates.sh` (`SEMGREP_IMAGE`, `OSV_IMAGE`, `TRIVY_IMAGE`, `SYFT_IMAGE`). Bump one, run its gate, and fix or accept what it finds. Trivy keeps its vulnerability database in the `hirevion-trivy-cache` Docker volume.
- **Dependencies of the licence check:** `pip-licenses` (a dev dependency) and `license-checker-rseidelsohn`, fetched by `pnpm dlx` at the version pinned in `licenses.py`. The Rust crates are checked by `cargo deny` (the `rust-licenses` job).

## Troubleshooting

| Problem | Fix |
|---|---|
| `hv up` fails with "port is already allocated" | Another program uses that port (often 80/443: IIS, Skype, another proxy). Stop it, or change the host port in `compose.yaml`. |
| ClamAV stays "starting" | The first start downloads about 300 MB of signatures. Wait, then `uv run hv logs clamav`. |
| `https://…hirevion.localhost` shows a certificate warning | Run `uv run hv trust-ca` again and restart the browser. |
| A Python/Node tool can't resolve `*.hirevion.localhost` | Run `uv run hv hosts`. |
| Docker runs out of memory | `%UserProfile%\.wslconfig` sets 10 GB for Docker (`[wsl2]` / `memory=10GB`). Stop `--obs` services when you don't need them. |
| You want a clean slate | `uv run hv reset`, then `uv run hv up`. |
