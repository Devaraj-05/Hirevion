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

## Daily commands

| Command | What it does |
|---|---|
| `uv run hv up` | Starts core, edge and media services and waits until they're healthy |
| `uv run hv up --obs` | Also starts Grafana (traces, logs, metrics) and GlitchTip (errors) |
| `uv run hv ps` | Shows containers and their health |
| `uv run hv logs [service]` | Follows logs, for example `uv run hv logs livekit` |
| `uv run hv smoke [--obs]` | Proves each service works with a real round-trip |
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
and 8001 on your PC; they answer once later sub-projects start those apps.

## Testing the third-eye camera from a phone

1. Put the phone on the same Wi-Fi as this PC.
2. Set `LIVEKIT_NODE_IP` in `.env` to this PC's LAN IP address (`ipconfig`), then `uv run hv up`.
3. Browsers only allow the camera on HTTPS pages, and the phone can't use Caddy's local
   certificate, so open the third-eye page through a quick tunnel:
   `cloudflared tunnel --url https://eye.hirevion.localhost --no-tls-verify`.
4. If Windows Firewall asks about Docker, allow it on private networks (UDP 7882, TCP 7881).

## Troubleshooting

| Problem | Fix |
|---|---|
| `hv up` fails with "port is already allocated" | Another program uses that port (often 80/443: IIS, Skype, another proxy). Stop it, or change the host port in `compose.yaml`. |
| ClamAV stays "starting" | The first start downloads about 300 MB of signatures. Wait, then `uv run hv logs clamav`. |
| `https://…hirevion.localhost` shows a certificate warning | Run `uv run hv trust-ca` again and restart the browser. |
| A Python/Node tool can't resolve `*.hirevion.localhost` | Run `uv run hv hosts`. |
| Docker runs out of memory | `%UserProfile%\.wslconfig` sets 10 GB for Docker (`[wsl2]` / `memory=10GB`). Stop `--obs` services when you don't need them. |
| You want a clean slate | `uv run hv reset`, then `uv run hv up`. |
