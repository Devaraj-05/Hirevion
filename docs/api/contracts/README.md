# Desktop API contracts

- **Readers:** the lanes that build these APIs (the providers) and lane B, which builds the desktop app (the consumer).
- **Purpose:** the APIs the candidate desktop app (and the third-eye phone page) call. Lane B drafted them on 2026-10-09 so the lanes can build in parallel.
- **Ownership:** the providing lane owns each file.
- **Changing a contract:**
  - Change a field or code only in a small PR that edits the contract file.
  - Add a dated line under "Changes" at the bottom of that file, so lane B sees it.
  - The OpenAPI document generated from the code must match the contract.

| File | Provider | Covers |
|---|---|---|
| [candidate-auth.md](candidate-auth.md) | Lane A (SP-07c) | Sign-in with §28's checks, one-time codes, device keys, tokens, desktop releases |
| [interview-session.md](interview-session.md) | Lane C (SP-09) | System checks, consents, starting the interview, LiveKit, candidate controls, completion |
| [proctoring.md](proctoring.md) | Lane C (SP-14) | Proctor sessions, signed and sequenced event batches, heartbeats, evidence uploads |
| [recordings.md](recordings.md) | Lane D (SP-12) | Segment upload URLs, hash-verified acknowledgement, recovery |
| [third-eye.md](third-eye.md) | Lane D (SP-13) | Pairing, redeeming on the phone, status, revocation |

## Conventions (all contracts)

**Base URL.** The desktop calls the API host directly: `https://api.hirevion.localhost/api/v1` locally, and the configured API origin in a release build. Paths below are relative to `/api/v1`.

**Errors.** RFC 9457 problem details, as everywhere in the API: `{"type", "title", "status", "detail", "code", ...}`. The desktop branches on `code` only, never on `title` or `detail`.

**Tokens.** All bearer tokens are DPoP-bound (RFC 9449):

- **Header.** Authenticated requests send `Authorization: DPoP <token>` and a `DPoP: <proof>` header.
- **The proof:**
  - a JWT with header `{"typ": "dpop+jwt", "alg": "ES256", "jwk": <device public key>}`;
  - claims `jti` (a fresh UUID), `htm` (the HTTP method) and `htu` (the URL without query or fragment);
  - claims `iat` (server time, see Clock), `ath` (base64url SHA-256 of the access token, when one is sent) and `nonce` (when the server asked for one).
- **What the server refuses** (`401` with code `dpop-invalid`):
  - a proof outside ±60 s;
  - a `jti` seen in the last 5 minutes (replay);
  - a key that isn't the one the token was issued to (`cnf.jkt`);
  - a missing or wrong `ath`.
- **Nonces.** The server may answer `401` with code `use-dpop-nonce` and a `DPoP-Nonce` header. The client retries once with that nonce, then keeps using the latest nonce it was given.
- **The device key** is an ECDSA P-256 key that never leaves the device. It is TPM-backed when available (Microsoft Platform Crypto Provider), otherwise the software key store.
  - Its identity is the RFC 7638 SHA-256 thumbprint of its public JWK (`jkt`).
  - The first sign-in from a key registers the device.

**Two token kinds:**

| Token | Lifetime | Scope | Used for |
|---|---|---|---|
| Access token | 10 minutes | `candidate` | Sign-in endpoints, the interview list, session-token requests |
| Interview-session token | Until the interview window closes, at most 4 hours | `interview`, one interview id | Everything in interview-session, proctoring, recordings and third-eye (desktop side) |

- **Refresh tokens:** opaque, rotating, valid at most 8 hours from sign-in. Using one twice revokes the whole family.
- **On the desktop:** the access and session tokens stay in Rust memory; the refresh token is kept in the DPAPI vault. None of them ever reaches the webview.

**Clock.** `GET /time` (already built) returns the server time as `received_at_ms` and `sent_at_ms`. The desktop keeps an offset and stamps every event and proof in server time.

**Idempotency.** A retried batch or segment is recognised by its sequence numbers (the proctoring and recording contracts say how), so retrying is always safe.

**Rate limits.** `429` with `Retry-After`. The desktop backs off exponentially, with jitter, capped at 30 s.

**App identity.** Every request sends `User-Agent: HirevionInterview/<version> (Windows <build>; <arch>)`.
