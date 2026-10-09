# Contract: candidate sign-in and desktop releases

**Provider:** lane A, SP-07c. **Consumer:** the desktop app (lane B, SP-08). The README holds the conventions.

## Sign in — `POST /candidate-auth/login`

- **Auth:** none, but it needs a `DPoP` proof (no `ath`). The proof's key becomes the device key.
- **Body:**

```json
{
  "email": "asha@example.test",
  "password": "…",
  "app": { "version": "1.4.0", "channel": "stable", "os": "Windows 11 26200", "arch": "x64" },
  "device": { "name": "ASHA-LAPTOP" }
}
```

The server checks §28's six items in this order. A failure answers with the code shown:

| # | Check | Failure |
|---|---|---|
| 1 | App version ≥ the channel's minimum | `426 app-update-required` with `minimum_version` and `download_url` |
| 2 | Candidate account exists, is active, and the password matches | `401 invalid-credentials` (also for unknown emails); `423 account-locked` with `Retry-After` |
| 3 | At least one assigned interview that is invited, in progress or interrupted | `403 no-interview` |
| 4 | That interview's job is open (not closed or archived) | `403 job-closed` |
| 5 | Its status allows starting or resuming | `403 interview-not-available` with `status` |
| 6 | It hasn't expired (window end > now) | `403 interview-expired` with `expired_at` |

Checks 3 to 6 consider every assigned interview: the login succeeds if any one interview passes all of them. The answer lists only the interviews that pass.

**200, signed in:**

```json
{
  "status": "ok",
  "access_token": "eyJ…",
  "token_type": "DPoP",
  "expires_in": 600,
  "refresh_token": "rt_…",
  "refresh_expires_in": 28800,
  "candidate": { "id": "uuid", "name": "Asha Rao", "email": "asha@example.test", "locale": "en-IN" },
  "organization": { "id": "uuid", "name": "Acme", "support_email": "help@acme.example.test" },
  "interviews": [
    {
      "id": "uuid",
      "job_title": "Backend Engineer",
      "status": "invited",
      "starts_at": "2026-10-12T04:30:00Z",
      "expires_at": "2026-10-13T18:29:59Z",
      "duration_minutes": 45,
      "third_eye": "optional",
      "proctoring_level": "standard",
      "coding": true
    }
  ]
}
```

**200, a one-time code is needed.** This happens when the organisation requires a code on new devices and this key hasn't been seen:

```json
{ "status": "otp_required", "challenge_id": "uuid", "sent_to": "a***@example.test", "expires_in": 600 }
```

## One-time codes

- **`POST /candidate-auth/otp/verify`**
  - Body: `{ "challenge_id": "uuid", "code": "123456" }`, with a `DPoP` proof from the same key.
  - `200`: the same body as a successful login.
  - Errors:
    - `400 otp-invalid` with `attempts_left`;
    - `410 otp-expired`;
    - `429 otp-attempts-exceeded` (after 5 tries the challenge is dead).
- **`POST /candidate-auth/otp/resend`**
  - Body: `{ "challenge_id": "uuid" }`.
  - `202`. At most once every 60 s, otherwise `429`.

## Tokens

- **`POST /candidate-auth/refresh`**
  - Body: `{ "refresh_token": "rt_…" }`, with a `DPoP` proof from the same key.
  - `200`: `{ "access_token", "token_type": "DPoP", "expires_in", "refresh_token", "refresh_expires_in" }`. The refresh token rotates, and the old one is dead.
  - Errors:
    - `401 refresh-invalid`;
    - `401 refresh-reused` (the family is revoked; the user signs in again);
    - `426 app-update-required`.
- **`POST /candidate-auth/logout`**
  - Auth: `Authorization: DPoP <access token>` plus a proof.
  - `204`. Revokes the refresh family.
- **`GET /candidate-auth/me`**
  - Auth: access token plus a proof.
  - `200`: `{ candidate, organization, interviews }`, as in the login answer. The desktop refreshes its interview list with it.

## Interview-session token — `POST /candidate-auth/interviews/{interview_id}/session-token`

- **Auth:** access token plus a proof.
- **`200`:**

```json
{
  "session_token": "eyJ…",
  "token_type": "DPoP",
  "expires_at": "2026-10-12T05:30:00Z",
  "interview": { "id": "uuid", "status": "invited", "starts_at": "…", "expires_at": "…", "duration_minutes": 45 }
}
```

- **Errors:**
  - `409 interview-not-open` with `starts_at` (the window hasn't started);
  - `410 interview-expired`;
  - `403 interview-not-available`.
- **The token's claims:** `sub` (the candidate account), `org`, `interview_id`, `scope: "interview"` and `cnf.jkt`. Its `exp` is the earliest of the window end, now + 4 hours, and the refresh family's end.

## Desktop releases

- **`GET /desktop/releases/check?version=1.4.0&channel=stable&arch=x64`**
  - Auth: none.
  - `200`:

```json
{
  "status": "ok | update-available | update-required",
  "latest": { "version": "1.5.0", "notes": "…", "published_at": "…" },
  "minimum_version": "1.3.0",
  "download_url": "https://downloads.hirevion.localhost/…"
}
```

  - Rollout percentages are applied per device, by hashing the `jkt` from an optional `DPoP` proof. Without a proof, the device counts as outside any partial rollout.
- **`GET /desktop/update-manifest/{target}/{arch}/{current_version}`**
  - The Tauri v2 updater format. `200`:

```json
{ "version": "1.5.0", "notes": "…", "pub_date": "2026-10-14T00:00:00Z",
  "platforms": { "windows-x86_64": { "signature": "<minisign signature>", "url": "https://…/AI-Interview_1.5.0_x64-setup.nsis.zip" } } }
```

  - `204` when no update applies.
  - The updater refuses a downgrade.

## Changes

- 2026-10-09: drafted by lane B.
- 2026-10-09: reviewed by lane A; no field changes. Clarified: a missing or malformed `DPoP` proof is `401 dpop-invalid`, like a replayed one; the server doesn't ask for nonces yet (`use-dpop-nonce` is reserved). Access tokens carry `iss`, `aud` (`hirevion-desktop`), `sub`, `org`, `scope`, `cnf.jkt`, `iat`, `exp` and `jti`; the desktop never needs to read them.
