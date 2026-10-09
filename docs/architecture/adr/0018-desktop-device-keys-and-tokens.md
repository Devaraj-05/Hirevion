# ADR-0018: Desktop sign-in: device-bound keys, DPoP, and tokens kept out of the webview

- **Status:** Accepted
- **Date:** 2026-10-09
- **Sub-project:** SP-08a (desktop) with SP-07c (API), contract `docs/api/contracts/candidate-auth.md`

## Context

- **PRD §8** asks the candidate desktop for:
  - short-lived credentials;
  - an interview-specific session token;
  - binding to the interview, the device and the session;
  - session expiry;
  - no master credentials in the app.
- **PRD §28** lists the six checks the backend makes at sign-in.
- **The master plan** (§3.2(5), §6.4, §9) adds three requirements:
  - a device-bound proof-of-possession key, TPM-backed where available;
  - a refresh token that never reaches the webview;
  - integrity checks reported as evidence rather than enforced blindly.
- **The threat** is a candidate who copies a token to another machine or a helper's browser, replays a captured request, or runs the app under a debugger or with WebView2 switched to a remote-debugging browser.

## Decision

- **The device key:**
  - **What it is:** an ECDSA P-256 key per Windows user, named `Hirevion Device Key v1`, created at first sign-in.
  - **Where it lives:** in the TPM through the Microsoft Platform Crypto Provider, or the software key storage provider when there's no usable TPM.
  - **Where that's recorded:** the server notes whether the key is hardware-backed, so reviewers can see it.
  - **Its identity:** the RFC 7638 thumbprint (`jkt`).
  - **New devices:** a sign-in with a new key needs the emailed one-time code when the organisation asks for it.
- **DPoP (RFC 9449) on every request.** Proofs carry `jti`, `htm`, `htu`, server-time `iat`, `ath` and the server's nonce when asked.
  - Access tokens (10 minutes) and interview-session tokens carry `cnf.jkt`.
  - The server refuses:
    - a proof from another key;
    - a proof outside ±60 s;
    - a `jti` replayed within 5 minutes.
- **Where tokens live:**
  - **Rust memory:** the access and interview-session tokens.
  - **A DPAPI file, current user:** the refresh token, rotating, with an 8-hour family. Reuse revokes the family.
  - **The webview** calls Tauri commands that return only what the screens show. It never holds a token or calls the API itself, and the CSP's `connect-src` has no API origin.
- **Integrity:**
  - **WebView2 settings:** before WebView2 starts, the app removes the environment variables that redirect the browser or add command-line switches, and records which were set.
  - **Debuggers:** a debugger is detected.
  - **Reporting:** both are reported as `CLIENT_INTEGRITY_WARNING` (SP-11). They are evidence for a reviewer, never an automatic refusal: assistive and corporate tools set some of them legitimately.
- **The update gate:** the release check runs before sign-in. A version below the channel's minimum stops at "Update required"; the sign-in API refuses it too (`426`). The signed updater and downgrade refusal come in SP-08b.

## Consequences

- **A stolen access or refresh token is useless elsewhere:** the matching private key can't be exported from the TPM, or from the user's key store without admin rights on that machine.
- **A compromised webview can't exfiltrate tokens,** because it never holds them.
- **Cost:** every request carries a signature (about 1 ms on the TPM, less in software). It also needs server time, which the client keeps from `GET /time`.
- **Machines without a TPM** fall back to a software key. That is weaker against an admin on the same machine, but recorded, so reviewers can see it.
