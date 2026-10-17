# ADR-0040: The third eye: a single-use pairing, LiveKit's view as its status, and Egress files beside the desktop's tracks

- **Status:** Accepted
- **Date:** 2026-10-17
- **Sub-project:** SP-13 (lane D, part D3)

## Context

- **PRD §52** asks for a phone's browser as a second camera, paired by QR code with a token that is short-lived, single-use, interview-bound, candidate-bound and revocable. **§53** says what it shows is evidence only; **§63** lists third-eye changes as events; **§92** draws the path through LiveKit.
- **ADR-0008** (the SP-00 spike) settled the transport: one HTTPS origin for the page and LiveKit's `/rtc` (a Cloudflare quick tunnel for phones in development), media on the LAN, a camera-only token in the URL fragment.
- **ADR-0032** made the server's own views the proctoring ground truth and left a `third_eye` channel waiting for LiveKit's events; **ADR-0030** made a required third eye unstartable without the waiver until pairing existed.
- **SP-12** (D2) moved the Egress of the conversation audio and the third eye's video here. Its `recordings` table and playback assume tracks assembled from the desktop's segments.

## Decision

- **Pairing** (`third_eye_pairings`, `hirevion_core.third_eye`):
  - The token is 256 random bits, stored only as its SHA-256, carried in the QR URL's fragment (`https://eye…/#t=`), which browsers never send. It must be redeemed within **2 minutes**, and redeeming spends it under a row lock: a second redeem is `410 token-used`.
  - The row holds the interview and its candidate (and the account whose desktop asked); the desktop's interview-session token must name that interview. A partial unique index allows **one live pairing per interview**.
  - **Issuing again revokes** the live pairing and removes its phone from the room (`RemoveParticipant`). A revoked phone that shows up again, before its LiveKit token runs out, is removed again when its webhook arrives.
  - The phone has no account, so the redeem finds the pairing through a `SECURITY DEFINER` lookup owned by `hirevion_auth` (the 0019 pattern), then works in the tenant.
- **The phone's LiveKit token** may join only `iv-{interview}` and publish only a camera: no microphone, screen, data or subscribing. It lives **10 minutes** (LiveKit refreshes it while the phone stays connected). Redeeming also answers a **device secret**, kept in the tab's `sessionStorage`; `POST /third-eye/rejoin` exchanges it for a fresh token, so a phone locked for longer reconnects without a new QR code. Revoking erases the secret.
- **`livekit_url` may be null:** the phone then connects to its page's own origin, which proxies `/rtc` (both local Caddy sites do; production sets `HV_THIRD_EYE_LIVEKIT_URL`). The phone's two calls are the only API routes its origin proxies.
- **Status is what LiveKit sees,** never what the phone says: the camera `track_published` makes the pairing `connected` (or `reconnected`), `track_unpublished` or `participant_left` makes it `disconnected`. Each change publishes `THIRD_EYE_STATUS` on the interview's stream and votes on SP-14's `third_eye` channel, which raises `THIRD_EYE_DISCONNECTED` after its 5 s debounce and grows it to WARNING (> 10 s) and CRITICAL (> 60 s when required). Only the current pairing votes, and deliveries older than the last one are ignored.
- **A locked phone within 10 s:** the page unpublishes its camera on `visibilitychange` (hidden) and `pagehide`, so LiveKit's webhook arrives within a second; with the 5 s debounce and the watcher's 1 s poll the event exists 6–7 s after the lock. On return it publishes again (rejoining if the room dropped); a drop while visible reconnects with backoff (1, 2, 4, 8, 15 s).
- **`start`** needs a `connected` pairing when the third eye is required (`409 third-eye-required`; the waiver still makes it optional). The **system check** stores the server's view of the third eye (`pass` when connected; `fail` when required, `warn` when optional, otherwise), replacing whatever the desktop reported.
- **Egress** (`hirevion_core.third_eye.egress`):
  - The conversation audio is a room-composite Egress, audio only (the candidate's microphone and the agent's voice mixed, `mp4`), started when the candidate joins a voice interview whose policy records audio; one runs at a time.
  - Each publication of the third eye's camera gets a track Egress (VP8 into `webm`, no transcoding) when the policy records cameras. The pairing remembers the track and the one recorded, so a phone paired before the start (as a required one must be) is recorded when the candidate joins the running interview, once per track.
  - Each run is a `recordings` row with `source = 'egress'` and a numbered track (`conversation-audio-N`, `third-eye-N`) in §85's `audio/` and `third-eye/` folders, planned before Egress starts so an early `egress_ended` still finds it. The assembly, its sweep, the continuity monitor and the desktop's recovery listing only take `source = 'desktop'`.
  - `egress_ended` queues `egress.ended`; the media worker makes the file a blob through an **`EgressOutput` adapter** (locally a Docker volume shared with the worker, which uploads and deletes the file; in the cloud Egress uploads to the container itself and the worker only reads its size and SHA-256), writes a one-span timeline map and marks the row `assembled`, so playback lists it like any track. A file that isn't there is retried, and fails after five attempts.
- **Development:** `hv eye-tunnel --page-only` opens the tunnel without a token and prints the `HV_THIRD_EYE_URL` to set, so the desktop's QR code points at it.

## Consequences

- **Measured pairing:** the phone-emulation path (headless Chromium with a fake 720p camera, the real local LiveKit) goes from opening the QR link to a live camera in about 1.6 s (`third-eye/e2e/pairing.spec.ts`); the server's part (issue, redeem, the webhook) takes milliseconds (`test_third_eye_api.py`). Real phones (iOS Safari 16.4+, Android Chrome), a real lock and the UDP-blocked fallback remain the owner's hands-on check.
- **A phone that dies without running JavaScript** (battery, a crash) is noticed only when LiveKit's own timeout drops it, so that case is flagged later than a lock (not measured yet; part of the owner's phone check).
- **The audio Egress runs headless Chrome** in the `egress` container (`SYS_ADMIN`). Its cost is per interview; the cloud plan sizes it.
- **`fps` is what the page asks for (15)**; LiveKit's webhook reports only the resolution.
- **For B4 (the desktop):** the pairing screen polls `GET /third-eye/pairings/{id}` every 2 s; during the interview the status is also on `THIRD_EYE_STATUS`; `start` answers `409 third-eye-required` until the phone's camera is live. These are recorded in the contract's "Changes".
- **The phone's rate limits count by address.** Behind Caddy every phone shares the proxy's address unless `HV_API_TRUSTED_PROXIES` is set, as it must be in production.
