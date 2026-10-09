# SP-08a Desktop foundation, part 1 — plan

- **Lane:** B (the local Windows PC).
- **Master plan:** §14 SP-08 and §6.4.
- **Contracts used:** `docs/api/contracts/candidate-auth.md` and `interview-session.md` (the system-check upload).

**Goal:** the desktop app goes from launch to an interview list, through:

1. a release check that can block an outdated app;
2. sign-in with a device-bound key (DPoP), with a one-time code on a new device;
3. the system check (PRD §29's eleven items plus Media Foundation and WebView2).

The real interview UI, consent, installers and signing are SP-08b.

## Decisions

- **One `security` crate (`hv-security`) owns the device key and everything that signs or stores secrets:**
  - **The device key:**
    - an ECDSA P-256 key per Windows user, named `Hirevion Device Key v1`;
    - held in the TPM through the Microsoft Platform Crypto Provider, falling back to the software key store when no TPM is usable;
    - its public key exported as a JWK, with its RFC 7638 thumbprint as the device id (`jkt`).
  - **DPoP proofs** follow the contracts README: ES256, `jti`, `htm`, `htu` without query, `iat`, `ath`, `nonce`.
  - **The vault:** DPAPI for the current user, one file per secret under `%LOCALAPPDATA%\Hirevion\vault`. It holds only the refresh token.
  - **Integrity:**
    - before WebView2 starts, the app removes the `WEBVIEW2_*` environment variables that change the browser (extra arguments, browser folder, user-data folder, channel), and records which were set;
    - a debugger check.

    Both are reported later as `CLIENT_INTEGRITY_WARNING` (SP-11).
- **The `api-client` crate (`hv-api-client`) sends every request from Rust:**
  - The webview never sees a token, and never calls the API itself (master plan §6.4).
  - TLS is reqwest with rustls, using the Windows certificate store, so the local Caddy CA and corporate CAs work.
  - Server time comes from `GET /time`: keep the sample with the shortest round trip.
  - A `401 use-dpop-nonce` is retried once with the server's nonce.
  - Problem documents become `ApiError::Problem { status, code, … }`.
  - The access token is refreshed when less than 60 s remain. The rotated refresh token goes back into the vault.
- **The `system-check` crate (`hv-system-check`) runs the native checks:**
  - CPU (logical cores and a 500 ms busy sample);
  - free memory and disk space;
  - display count;
  - the Windows camera and microphone privacy settings, which give `ms-settings:` links when denied;
  - the Media Foundation H.264 encoder;
  - the OS build;
  - a screen-capture probe: one frame per display through the existing `hv-screen-capture` crate.

  The webview runs the checks that need its media stack: camera, microphone level, speaker (a tone plus a confirmation), and network (round trip to the API through Rust).
  - **LiveKit connectivity** is checked when the interview starts (SP-08b), since it needs a room token.
  - **Third-eye** is `skipped` until SP-13.
- **Thresholds:**

  | Check | Pass | Warn | Fail |
  |---|---|---|---|
  | CPU | ≥ 4 logical cores, < 80% busy | | |
  | Memory | ≥ 2 GB free | ≥ 1 GB free | below that |
  | Disk | ≥ 5 GB free | ≥ 2 GB free | below that |
  | Displays | 1 | more than 1 (fail under a single-display policy) | |
  | Microphone peak | above -50 dBFS over 3 s | | |
  | Camera | ≥ 640×480 at 15 fps | | |

  - Which checks are mandatory comes from the interview's policy. Until SP-14, camera, microphone, screen capture and Media Foundation are mandatory.
- **The app (`src-tauri/src/app/`):**
  - **Tauri commands** take the place of the API for the webview: `app_info`, `release_check`, `sign_in`, `verify_code`, `resend_code`, `sign_out`, `interviews`, `native_checks`, `api_round_trip` and `submit_checks`. They return only what the screens show.
  - **Errors:** a command error is `{ code, detail }`, and the screens translate `code`.
  - **Single instance:** `tauri-plugin-single-instance`.
  - **Integrity first:** environment sanitising runs before Tauri starts.
  - **The API URL** is compiled in (`HV_API_URL`, default `https://api.hirevion.localhost/api/v1`). Debug builds may override it at run time.
- **The webview:**
  - React with the design system (`@hirevion/ui` through Tailwind v4, as in the web app);
  - en-IN and en-US through `use-intl`;
  - routes: launch → sign-in → code → interviews → system check → ready (a placeholder until SP-08b).
  - The spike pages stay reachable in debug builds only.
- **Not in 08a:** the updater plugin and signing, consent, the interview shell and installers (all SP-08b); the native monitors (SP-11); recording (SP-12).

## Interfaces (the parallel subagents build against these)

```rust
// hv-security
pub trait Signer: Send + Sync {
    fn public_jwk(&self) -> Jwk;            // {"kty":"EC","crv":"P-256","x","y"}, base64url
    fn thumbprint(&self) -> String;         // RFC 7638 SHA-256, base64url
    fn sign(&self, message: &[u8]) -> Result<[u8; 64], SecurityError>; // ES256 r||s over SHA-256(message)
    fn hardware_backed(&self) -> bool;
}
pub struct Jwk { pub kty: String, pub crv: String, pub x: String, pub y: String } // Serialize, Deserialize, Clone
pub struct SoftwareKey;                     // p256; SoftwareKey::generate()
#[cfg(windows)] pub struct NcryptKey;       // NcryptKey::open_or_create(name, prefer_tpm) -> Result<Self>; .delete()
pub mod dpop {
    pub fn proof(signer: &dyn Signer, method: &str, url: &str, access_token: Option<&str>,
                 nonce: Option<&str>, iat_unix: i64) -> Result<String, SecurityError>;
}
pub struct Vault;                           // Vault::new(dir); put(name, &[u8]); get(name) -> Option<Vec<u8>>; delete(name)
pub mod integrity { pub fn sanitize_webview_environment() -> Vec<String>; pub fn debugger_present() -> bool; }

// hv-api-client
pub struct ApiClient;  // ApiClient::new(base: Url, signer: Arc<dyn Signer>, user_agent: String) -> Result<Self, ApiError>
impl ApiClient {
    pub async fn sync_clock(&self) -> Result<ClockSample, ApiError>;  // GET /time
    pub fn server_now_ms(&self) -> i64;
    pub async fn send<B: Serialize + ?Sized, T: DeserializeOwned>(&self, method: Method, path: &str,
        body: Option<&B>, token: Option<&str>) -> Result<T, ApiError>;
    pub async fn send_no_content<B: Serialize + ?Sized>(&self, method: Method, path: &str,
        body: Option<&B>, token: Option<&str>) -> Result<(), ApiError>;
}
pub enum ApiError { Problem { status: u16, code: String, detail: Option<String>, retry_after: Option<u64>,
    body: serde_json::Value }, Network(String), Decode(String), Security(String) }
pub mod auth {   // candidate-auth.md, field for field
    pub async fn login(api: &ApiClient, req: &LoginRequest) -> Result<LoginOutcome, ApiError>;
    pub async fn verify_otp(api, &OtpVerify) -> Result<LoginOutcome, ApiError>;
    pub async fn resend_otp(api, challenge_id) -> Result<(), ApiError>;
    pub async fn refresh(api, refresh_token) -> Result<TokenPair, ApiError>;
    pub async fn logout(api, access_token) -> Result<(), ApiError>;
    pub async fn me(api, access_token) -> Result<Me, ApiError>;
    pub async fn session_token(api, access_token, interview_id) -> Result<SessionToken, ApiError>;
    pub async fn release_check(api, version, channel, arch) -> Result<ReleaseCheck, ApiError>;
}
pub struct SessionManager; // owns ApiClient + Vault; sign_in/verify -> stores tokens; access_token() refreshes; sign_out()

// hv-system-check
pub enum Status { Pass, Warn, Fail, Skipped }          // serde: "pass" | "warn" | "fail" | "skipped"
pub struct CheckResult { pub check: String, pub status: Status, pub value: Option<String>, pub detail: Option<String> }
pub fn native_checks() -> Vec<CheckResult>;           // cpu, memory, disk, displays, privacy, media_foundation, os
pub fn screen_capture_probe() -> CheckResult;          // check = "screen_capture"
```

## Tasks

1. **The `security` crate** (subagent 1, worktree). Tests:
   - a software-key DPoP proof verifies under its JWK, and its claims are right;
   - the thumbprint matches the RFC 7638 example;
   - an NcryptKey round trip with the software provider;
   - the DPAPI vault: a round trip, and a missing secret;
   - sanitising removes the listed variables.
2. **The `api-client` crate** (subagent 1). Tests against `wiremock`:
   - the DPoP header is present and its `ath` matches;
   - the nonce retry happens once;
   - problems are parsed;
   - the clock offset is computed;
   - refresh rotation lands in the vault;
   - sign-in maps both 200 answers.
3. **The `system-check` crate** (subagent 2, worktree). Tests: a value and status for every check on the CI runner, and threshold mapping as pure functions.
4. **The webview checks** (subagent 2, `src/checks/`). Vitest for the dBFS maths, the thresholds and the payload builder.
5. **The app** (main session):
   - the commands and state;
   - `main.rs` integrity-first and single instance;
   - Tailwind and the design system;
   - i18n;
   - the screens and the launch-flow state machine, with Vitest;
   - debug-only spikes.
6. **Docs:** ADR-0018 (desktop device keys, DPoP and where tokens live), the runbook, the threat-model section, the PENDING_TASKS box.

## Exit for 08a

- With the API's SP-07c endpoints (or a stub server when they're missing), a debug build:
  - signs in;
  - asks for a code on a new device;
  - lists interviews;
  - runs every check and uploads the results.
- `cargo fmt`, `clippy -D warnings` and `cargo test` pass, plus `pnpm --filter @hirevion/ai-interviewer-desktop typecheck test`.
