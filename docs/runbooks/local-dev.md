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

## Voice agent and latency benchmark

The spike agent (`backend/interview_agent`) is a LiveKit Agents worker: Deepgram speech-to-text
and text-to-speech, Gemini through its OpenAI-compatible API, and LiveKit's local turn detector.
Settings come from `HV_*` in `.env` and are read at the start of each session.

1. `uv run python -m hirevion_interview_agent.agent download-files` once. It fetches the voice
   detector and, with `HV_TURN_DETECTION=multilingual`, the turn-detector model (about 70 MB).
2. `uv run python -m hirevion_interview_agent.agent dev` with `uv run hv up` already running.
   Restart it after changing agent code or `HV_TURN_DETECTION`.
3. `uv run hv-voice-bench --turns 20` plays a synthetic candidate and prints the time from the
   end of each answer to the agent's first audio (p50/p95), with the agent's own stage
   breakdown.

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
   - the super admin `super@hirevion.example.test` in the Platform organisation.

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
5. **Locked out.** Five wrong passwords lock the email for a minute, doubling up to an hour.
   Locks are Valkey keys named `lockout:<SHA-256 of the lower-cased email>`;
   `docker exec hirevion-valkey-1 valkey-cli -a <VALKEY_PASSWORD> --scan --pattern "lockout:*"`
   lists them, and deleting one unlocks that email.
6. **Breached-password check.** New passwords are checked against a bundled list and, with
   `HV_HIBP_ENABLED=true` (the default), the Have I Been Pwned range API. Only the first five
   characters of the password's SHA-1 leave the PC. Set it to `false` offline.

**End-to-end sign-in suite.** With the stack up, `hv seed-identity` done and `uv run hv api`
running:

```sh
HV_E2E_API=1 pnpm --filter @hirevion/recruitment-platform e2e
```

It builds the web app without development sessions, serves it on port 3101 behind a small
gateway on 3100 (standing in for Caddy), and signs in, resets passwords, changes email addresses
and revokes sessions for real, reading the emails from Mailpit. It invites its own super admins
with `uv run hv create-super-admin`; set `HV_UV` to uv's full path if `uv` isn't on `PATH`.

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

Press Ctrl+C in the `eye-tunnel` terminal as soon as you're done: while it runs, the page and
LiveKit signalling are reachable at a public (random) address. Docker Desktop's installer already
allows its backend through Windows Firewall. If the phone connects but shows no video, check the
firewall allows UDP 7882 and TCP 7881 for "Docker Desktop Backend".

## Troubleshooting

| Problem | Fix |
|---|---|
| `hv up` fails with "port is already allocated" | Another program uses that port (often 80/443: IIS, Skype, another proxy). Stop it, or change the host port in `compose.yaml`. |
| ClamAV stays "starting" | The first start downloads about 300 MB of signatures. Wait, then `uv run hv logs clamav`. |
| `https://…hirevion.localhost` shows a certificate warning | Run `uv run hv trust-ca` again and restart the browser. |
| A Python/Node tool can't resolve `*.hirevion.localhost` | Run `uv run hv hosts`. |
| Docker runs out of memory | `%UserProfile%\.wslconfig` sets 10 GB for Docker (`[wsl2]` / `memory=10GB`). Stop `--obs` services when you don't need them. |
| You want a clean slate | `uv run hv reset`, then `uv run hv up`. |
