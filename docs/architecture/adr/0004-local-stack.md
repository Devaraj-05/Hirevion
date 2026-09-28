# ADR-0004: Local Docker stack

- **Status:** Accepted
- **Date:** 2026-09-28
- **Sub-project:** SP-00b

## Context

Every sub-project needs the same infrastructure locally: PostgreSQL with pgvector, a Redis-compatible store, Azure-compatible blob storage, malware scanning, email, LiveKit and HTTPS for `*.hirevion.localhost`. It must run on a 16 GB Windows PC next to VS Code and a browser, and move to Azure later with configuration only (master plan §5.4).

## Decision

- One compose file, `infrastructure/local/compose.yaml`, project `hirevion`, with profiles: `core` (postgres, valkey, azurite, clamav, mailpit), `edge` (caddy), `media` (livekit) and `obs` (otel-lgtm, glitchtip in all-in-one mode).
- Images are pinned by digest.
- Host ports bind to `127.0.0.1`, except LiveKit's media ports (7881/tcp, 7882/udp), which a phone on the LAN must reach.
- Secrets are generated per developer into the gitignored `.env` (`hv init-env`, `hv env-sync`). No shared passwords; Azurite uses a generated account and key instead of the public development key.
- Valkey replaces Redis locally (BSD licence, protocol-compatible with Azure Managed Redis).
- Caddy serves `https://*.hirevion.localhost` with its own local CA. `hv trust-ca` trusts it for the current Windows user, and `hv hosts` adds hosts-file entries because Windows (unlike browsers) doesn't resolve `*.localhost` names.
- `hv smoke` proves each service with a real round-trip; `hv doctor` checks tools, hostnames and keys.

## Consequences

- `core` + `edge` + `media` use about 1.3 GB of memory (ClamAV is most of it); `obs` is optional.
- First-time setup asks for two confirmations: admin rights for the hosts file and the certificate-install dialog.
- Upgrading an image is a deliberate change: pull the new tag, pin its digest, run `hv smoke`.
