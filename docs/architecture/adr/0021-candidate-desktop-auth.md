# ADR-0021: Candidate desktop sign-in: DPoP-bound tokens, refresh families, new-device codes and a release registry

- **Status:** Accepted
- **Date:** 2026-10-09
- **Sub-project:** SP-07c

## Context

- **PRD §8** asks the desktop app for email and password sign-in, short-lived tokens, an interview-session token, device and session binding, and no master credentials in the app. **PRD §28** lists six checks at sign-in; **§26** starts with a version check.
- **`docs/api/contracts/candidate-auth.md`** (lane B, reviewed by lane A) fixes the wire format: DPoP (RFC 9449) on every request, a 10-minute access token, an 8-hour rotating refresh token, an interview-session token, an emailed code on a new device, the release check and the Tauri update manifest.
- **The desktop is an untrusted client** on the candidate's machine (master plan §3.2(5)): a token copied off it must be useless elsewhere.
- **Candidate accounts are per organisation** (ADR-0020), found by email before the tenant is known.

## Decision

- **Every desktop request proves the device key.** The `DPoP` header is a JWT signed by the device's P-256 key, which it carries in its header. The server accepts ES256 only, a public P-256 `jwk`, `htm`/`htu` matching the request (scheme, host and path), `iat` within ±60 s, and an unseen `jti` per key for 5 minutes (Valkey `SET NX EX`). With a token, `ath` must hash it and the key's RFC 7638 thumbprint must equal the token's `cnf.jkt`. Every refusal is `401 dpop-invalid` with `WWW-Authenticate: DPoP`. No nonces yet.
- **Tokens are ES256 JWTs** signed with `HV_CANDIDATE_TOKEN_KEY` (base64 PKCS #8; `hv init-env` and `env-sync` generate one). Outside production a missing key is derived from the install's database password (HMAC-SHA-512 to a P-256 scalar), with a warning, so every API process of one install agrees; production refuses to start without one. Claims: `iss`, `aud` `hirevion-desktop`, `sub` (the account), `org`, `scope`, `cnf.jkt`, `sid` (the refresh family), `iat`, `exp`, `jti`; session tokens add `interview_id`.
  - **Access** (`candidate`): 10 minutes.
  - **Interview session** (`interview`): until the earliest of the window's end plus the interview's duration, now + 4 hours, and the family's end.
- **Refresh tokens** are `rt_` + 256 random bits, stored as SHA-256 (`candidate_refresh_tokens`), one family per sign-in, 8 hours absolute, bound to the device. Each use rotates; a spent one coming back revokes the whole family (`refresh-reused`) and is audited. Every request with an access or session token checks its family is live and its device not revoked, so sign-out, reuse detection and device revocation take effect at once rather than when tokens expire. Refresh checks the channel's minimum against the version in the `User-Agent`, else the version the device last reported.
- **Devices** (`candidate_devices`): the key's thumbprint and public key, its name and app details. When the organisation's "code on a new device" is on (`organization_settings.candidate_access.new_device_otp`, default on), a key's first sign-in gets a 6-digit code by email instead of tokens (`candidate_otps`: HMAC-SHA-256 under a key derived from the signing key, 10 minutes, 5 attempts, a resend at most every 60 s and 5 sends in all). Only the key that asked can answer or ask for a resend, and a resend never resets the attempts: after the fifth wrong code the challenge is dead.
- **§28's six checks, in order:** the app version against its channel's minimum (`426`); the account and password (the same `401` for unknown emails after the same argon2 work; `423` after the recruiter lockout's rules, keyed apart from recruiters'); then over every interview the candidate was invited to: one exists, its job is open, its status is invited, in progress or interrupted, and its window isn't over. Sign-in succeeds when one interview passes them all, and lists those. A person with accounts in several organisations signs in where the password matches and an interview is waiting (the soonest).
- **Two lookups before the tenant is known** (`auth_candidate_refresh`, `auth_candidate_otp`) are SECURITY DEFINER functions owned by `hirevion_auth`, as ADR-0013's are.
- **The release registry** is platform data (no `organization_id`): `desktop_channels` (`stable`, `beta`, each with a minimum version and a download address) and `desktop_releases` (version, channel, architecture, URL, minisign signature, notes, status, rollout percentage). Versions are semantic, pre-releases first. A device is in a partial rollout when `sha256("{jkt}:{version}")` falls in the first `rollout_percent` buckets, so the answer is stable per device and widening only adds devices; without a proof only full rollouts count. The Tauri v2 manifest never offers a version at or below the running one (`204`). Super admins manage it at `/platform/desktop-releases`, with step-up, audited in the platform chain.
- **Routes:** `/candidate-auth/*` and `/desktop/*`. The authorisation matrix lists them as unguarded with their kind: `device` (a proof), `candidate` (an access token), `public` (the release check and manifest).
- **Contract changes** recorded in `candidate-auth.md`: `interview_status` (RFC 9457 already uses `status`), `401 token-invalid`, the session token's longer end, `404 interview-not-found`, and the app version read from the `User-Agent` at refresh.

## Consequences

- **A copied token is useless without the device's private key**, which the desktop keeps in the TPM where it can (SP-08a); replays inside the window are caught by `jti`.
- **Rotating `HV_CANDIDATE_TOKEN_KEY` signs everyone out** (and invalidates pending codes). The cloud plan should add a `kid`-keyed set for overlap.
- **Every candidate request costs one indexed family lookup.** Cache it with a short TTL if it shows up in traces.
- **SP-09, SP-12, SP-13 and SP-14** guard their desktop routes with the interview-session token (`interview_principal`), which also checks the path's interview.
- **SP-22** adds the candidate-access setting to the security page alongside MFA policy; device lists and revocation per candidate come with the portal (SP-07b) and support tooling (SP-23).
