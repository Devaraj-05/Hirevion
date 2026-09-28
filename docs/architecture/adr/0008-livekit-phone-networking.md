# ADR-0008: Third-eye phone and desktop on self-hosted LiveKit (local development)

- **Status:** Accepted
- **Date:** 2026-09-29
- **Sub-project:** SP-00d (spike 4)

## Context

The third-eye camera is a phone's browser page (PRD §52). Phone browsers only allow the camera on HTTPS pages. A phone can't use this PC's `*.hirevion.localhost` names or trust Caddy's local certificate authority. LiveKit runs in Docker Desktop, and its media must reach both the desktop app on this PC and a phone on the same Wi-Fi.

Tested on the development PC, whose Wi-Fi is on Windows' Public profile. The "phone" was headless Edge with a fake 720p camera, reaching the page through a real Cloudflare quick tunnel. The desktop app joined the same room with a spike page that records WebRTC statistics.

| Measurement | Result |
|---|---|
| Phone page through the tunnel | 200. LiveKit signalling on the same origin (`/rtc`) answered through the tunnel. |
| Phone joined and published | 1280×720 camera track; LiveKit room API shows the participant active |
| Desktop join (signalling via `wss://livekit.hirevion.localhost`) | 1.9 s; first phone frame at 2.0 s |
| Media path | UDP, host ↔ peer-reflexive candidate (Docker Desktop's port proxy), RTT 1–3 ms |
| Video at the desktop | 1280×720, 14–15 fps, about 480 kbps, 0 packets lost, 0 reconnects in 40 s |
| Desktop app CPU while watching | 2.7 % |

Problems found on the way:

- **Vite and Docker disagree on "localhost".** Vite's default `localhost` listened only on IPv6 (`[::1]`), while Docker Desktop forwards `host.docker.internal` to IPv4, so Caddy got a 502.
- **Two command-line traps:** `cmd.exe start` splits URLs at `&`, and Git Bash rewrites container paths such as `/etc/...` unless `MSYS_NO_PATHCONV=1` is set.

## Decision

- **Tunnel.**
  - `uv run hv eye-tunnel` starts a Cloudflare quick tunnel to Caddy's plain-HTTP tunnel site (`127.0.0.1:8088`). There `/rtc*` goes to LiveKit and everything else to the third-eye dev server, so the phone uses one HTTPS origin for the page and for signalling.
  - The command mints a camera-publish-only token (30 minutes) and prints the phone link and a QR code.
  - The token is in the URL fragment (`#t=`), which the browser never sends, so it stays out of Cloudflare, Caddy and Vite logs.
- **Media stays on the LAN.**
  - `LIVEKIT_NODE_IP` is set to this PC's LAN address, and LiveKit advertises it for its media ports (7881/tcp, 7882/udp).
  - Those two ports are the only ones published beyond loopback; everything else binds to `127.0.0.1`. Docker Desktop's installer already allows its backend through Windows Firewall.
  - `hv eye-tunnel` refuses to start while the node IP is loopback, and suggests the detected LAN address.
- **Dev servers bind to `127.0.0.1` explicitly.** This applies to every dev server behind Caddy (the web app later too).
- **Tokens.**
  - The phone gets a token that can only publish a camera (`canPublishSources: ["camera"]`, no subscribing, no data).
  - The desktop's development token comes from `uv run hv lk-token`.
  - No LiveKit secret exists in either app.
- **Allowed hosts.** Vite's `allowedHosts` accepts only `.trycloudflare.com` and `eye.hirevion.localhost` (it answered 403 for any other host), guarding the dev server against DNS rebinding.

## Consequences

- **The tunnel is public.**
  - While `hv eye-tunnel` runs, the third-eye dev server and LiveKit signalling are reachable at a random public URL. Signalling still needs a token.
  - Run the tunnel only while testing. Ctrl+C closes it.
- **Hands-on tests are still needed** before SP-13 builds on this:
  - a real phone on iOS Safari 16.4+ and on Android Chrome, over the same Wi-Fi, scanning the QR code;
  - locking the phone and noting the reconnect time;
  - forcing TCP by blocking UDP 7882, to check the fallback.
- **SP-13:**
  - The backend issues single-use pairing tokens (PRD §52), replacing `hv eye-tunnel`'s development token.
  - The page moves to the production host.
- **Cloud Migration Plan:**
  - Phones on mobile data, or on networks that block UDP, need TURN (LiveKit's built-in TURN over TLS 5349 or UDP 3478, or LiveKit Cloud).
  - Azure Container Apps cannot expose UDP (master plan §3.2).
