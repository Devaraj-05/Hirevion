# Contract: third-eye pairing

**Provider:** lane D, SP-13. **Consumers:**

- the desktop app (lane B: the pairing screen, using the interview-session token plus DPoP);
- the `third-eye/` phone page (lane D, no account).

## Desktop: issue a pairing — `POST /third-eye/pairings`

- **Body:** `{ "interview_id": "uuid" }`.
- **`201`:**

```json
{
  "pairing_id": "uuid",
  "qr_url": "https://eye.hirevion.localhost/#t=<token>",
  "expires_at": "2026-10-12T05:00:00Z",
  "status": "issued"
}
```

- **The token** has all five of §52's properties:
  - short-lived (2 minutes until it's redeemed);
  - single-use;
  - bound to the interview;
  - bound to the candidate;
  - revocable.
- **The token is in the URL fragment** (`#t=`), which a browser never sends, so it stays out of server and proxy logs; the phone page reads it and spends it with `POST /third-eye/redeem`.
- **Pairing again** revokes the previous pairing and disconnects its phone.

## Desktop: watch the pairing

`GET /third-eye/pairings/{pairing_id}` returns `200`:

```json
{
  "status": "issued | redeemed | connected | disconnected | revoked | expired",
  "expires_at": "…",
  "device": { "platform": "iOS 18 Safari" },
  "connected_at": "…",
  "last_seen_at": "…",
  "video": { "width": 1280, "height": 720, "fps": 15 }
}
```

- **Before the interview,** the desktop polls every 2 s during setup.
- **During the interview,** the status comes through `hv.state` notices and server events (`THIRD_EYE_STATUS`, §91).

`POST /third-eye/pairings/{pairing_id}/revoke` returns `204`.

## Phone: redeem — `POST /third-eye/redeem`

- **Auth:** none; the token is the credential, and it is spent here.
- **Body:** `{ "token": "<token from the QR URL>", "device": { "user_agent": "…" } }`.
- **`200`:**

```json
{
  "livekit_url": "wss://livekit.hirevion.localhost",
  "participant_token": "eyJ…",
  "participant_identity": "third-eye-<uuid>",
  "expires_at": "…",
  "interview": { "company": "Acme", "job_title": "Backend Engineer" },
  "placement": { "distance_m": 1.5, "angle": "side-rear", "show": ["face", "hands", "desk", "screen"] }
}
```

- **The participant token** can publish one camera track and nothing else: no microphone, no data, no subscribing.
- **Errors:** `410 token-used`, `410 token-expired`, `410 pairing-revoked`.
- **Status reporting:** the phone reports nothing directly. The server sees it connect and disconnect through LiveKit webhooks, which drive the pairing status and the `THIRD_EYE_DISCONNECTED` event.

## Changes

- 2026-10-09: drafted by lane B.
- 2026-10-09: reviewed by lane D. `qr_url` carries the token in the fragment (`/#t=<token>`) instead of the path, as the SP-00 spike's phone page already reads it, so it never reaches a server log. `GET /third-eye/pairings/{pairing_id}` also answers `expires_at`.
