//! Candidate sign-in and desktop releases: `docs/api/contracts/candidate-auth.md`, field for field.
//!
//! Token-bearing types redact their tokens (and the password) in `Debug` output.

use std::fmt;

use reqwest::Method;
use serde::{Deserialize, Serialize};

use crate::{ApiClient, ApiError};

/// `POST /candidate-auth/login` body.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LoginRequest {
    pub email: String,
    pub password: String,
    pub app: AppInfo,
    pub device: DeviceInfo,
}

impl fmt::Debug for LoginRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LoginRequest")
            .field("email", &self.email)
            .field("password", &Redacted)
            .field("app", &self.app)
            .field("device", &self.device)
            .finish()
    }
}

/// The app that is signing in.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AppInfo {
    pub version: String,
    pub channel: String,
    pub os: String,
    pub arch: String,
}

/// The device that is signing in.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DeviceInfo {
    pub name: String,
}

/// The two `200` answers of login and code verification, told apart by `status`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum LoginOutcome {
    /// `"status": "ok"`: signed in. (Boxed: it is much larger than the challenge.)
    Ok(Box<SignedIn>),
    /// `"status": "otp_required"`: a one-time code was sent.
    OtpRequired(OtpChallenge),
}

/// A successful sign-in.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SignedIn {
    pub access_token: String,
    pub token_type: String,
    pub expires_in: u64,
    pub refresh_token: String,
    pub refresh_expires_in: u64,
    pub candidate: Candidate,
    pub organization: Organization,
    pub interviews: Vec<Interview>,
}

impl fmt::Debug for SignedIn {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SignedIn")
            .field("access_token", &Redacted)
            .field("token_type", &self.token_type)
            .field("expires_in", &self.expires_in)
            .field("refresh_token", &Redacted)
            .field("refresh_expires_in", &self.refresh_expires_in)
            .field("candidate", &self.candidate)
            .field("organization", &self.organization)
            .field("interviews", &self.interviews)
            .finish()
    }
}

/// A one-time code was sent.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OtpChallenge {
    pub challenge_id: String,
    pub sent_to: String,
    pub expires_in: u64,
}

/// The signed-in candidate.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Candidate {
    pub id: String,
    pub name: String,
    pub email: String,
    pub locale: String,
}

/// The candidate's organisation.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Organization {
    pub id: String,
    pub name: String,
    /// Missing until the organisation sets one.
    #[serde(default)]
    pub support_email: Option<String>,
}

/// An interview the candidate may start or resume. Times are RFC 3339 strings.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Interview {
    pub id: String,
    pub job_title: String,
    pub status: String,
    pub starts_at: String,
    pub expires_at: String,
    pub duration_minutes: u32,
    pub third_eye: String,
    pub proctoring_level: String,
    pub coding: bool,
}

/// `POST /candidate-auth/otp/verify` body.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OtpVerify {
    pub challenge_id: String,
    pub code: String,
}

/// `POST /candidate-auth/refresh` answer. The refresh token rotates.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TokenPair {
    pub access_token: String,
    pub token_type: String,
    pub expires_in: u64,
    pub refresh_token: String,
    pub refresh_expires_in: u64,
}

impl fmt::Debug for TokenPair {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("TokenPair")
            .field("access_token", &Redacted)
            .field("token_type", &self.token_type)
            .field("expires_in", &self.expires_in)
            .field("refresh_token", &Redacted)
            .field("refresh_expires_in", &self.refresh_expires_in)
            .finish()
    }
}

/// `GET /candidate-auth/me` answer.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Me {
    pub candidate: Candidate,
    pub organization: Organization,
    pub interviews: Vec<Interview>,
}

/// `POST /candidate-auth/interviews/{id}/session-token` answer.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SessionToken {
    pub session_token: String,
    pub token_type: String,
    pub expires_at: String,
    pub interview: SessionInterview,
}

impl fmt::Debug for SessionToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SessionToken")
            .field("session_token", &Redacted)
            .field("token_type", &self.token_type)
            .field("expires_at", &self.expires_at)
            .field("interview", &self.interview)
            .finish()
    }
}

/// The interview a session token is for.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SessionInterview {
    pub id: String,
    pub status: String,
    pub starts_at: String,
    pub expires_at: String,
    pub duration_minutes: u32,
}

/// `GET /desktop/releases/check` answer.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseCheck {
    pub status: ReleaseStatus,
    #[serde(default)]
    pub latest: Option<ReleaseInfo>,
    pub minimum_version: String,
    #[serde(default)]
    pub download_url: Option<String>,
}

/// Whether this version may run.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReleaseStatus {
    Ok,
    UpdateAvailable,
    UpdateRequired,
}

/// The latest release on the channel.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReleaseInfo {
    pub version: String,
    pub notes: String,
    pub published_at: String,
}

/// Signs in. The proof's key becomes the device key.
pub async fn login(api: &ApiClient, request: &LoginRequest) -> Result<LoginOutcome, ApiError> {
    api.send(Method::POST, "candidate-auth/login", Some(request), None)
        .await
}

/// Verifies a one-time code (with a proof from the same key as the login).
pub async fn verify_otp(api: &ApiClient, request: &OtpVerify) -> Result<LoginOutcome, ApiError> {
    api.send(
        Method::POST,
        "candidate-auth/otp/verify",
        Some(request),
        None,
    )
    .await
}

/// Sends the one-time code again (at most once every 60 s).
pub async fn resend_otp(api: &ApiClient, challenge_id: &str) -> Result<(), ApiError> {
    #[derive(Serialize)]
    struct Resend<'a> {
        challenge_id: &'a str,
    }
    api.send_no_content(
        Method::POST,
        "candidate-auth/otp/resend",
        Some(&Resend { challenge_id }),
        None,
    )
    .await
}

/// Trades the refresh token for new tokens. The old refresh token is dead afterwards.
pub async fn refresh(api: &ApiClient, refresh_token: &str) -> Result<TokenPair, ApiError> {
    #[derive(Serialize)]
    struct Refresh<'a> {
        refresh_token: &'a str,
    }
    api.send(
        Method::POST,
        "candidate-auth/refresh",
        Some(&Refresh { refresh_token }),
        None,
    )
    .await
}

/// Revokes the refresh family.
pub async fn logout(api: &ApiClient, access_token: &str) -> Result<(), ApiError> {
    api.send_no_content::<()>(
        Method::POST,
        "candidate-auth/logout",
        None,
        Some(access_token),
    )
    .await
}

/// The candidate, organisation and current interview list.
pub async fn me(api: &ApiClient, access_token: &str) -> Result<Me, ApiError> {
    api.send::<(), _>(Method::GET, "candidate-auth/me", None, Some(access_token))
        .await
}

/// An interview-session token for one interview.
pub async fn session_token(
    api: &ApiClient,
    access_token: &str,
    interview_id: &str,
) -> Result<SessionToken, ApiError> {
    let path = format!(
        "candidate-auth/interviews/{}/session-token",
        path_segment(interview_id)?
    );
    api.send::<(), _>(Method::POST, &path, None, Some(access_token))
        .await
}

/// Whether this app version may run, and what to update to. Sent with a proof so the server
/// can place this device in a staged rollout.
pub async fn release_check(
    api: &ApiClient,
    version: &str,
    channel: &str,
    arch: &str,
) -> Result<ReleaseCheck, ApiError> {
    let query = url::form_urlencoded::Serializer::new(String::new())
        .append_pair("version", version)
        .append_pair("channel", channel)
        .append_pair("arch", arch)
        .finish();
    api.send::<(), _>(
        Method::GET,
        &format!("desktop/releases/check?{query}"),
        None,
        None,
    )
    .await
}

/// Percent-encodes everything but RFC 3986 unreserved characters, for one path segment.
///
/// Empty, `.` and `..` are refused: URL parsing resolves dot-segments even when
/// percent-encoded, so they can't be escaped into a literal segment.
fn path_segment(value: &str) -> Result<String, ApiError> {
    if matches!(value, "" | "." | "..") {
        return Err(ApiError::Security(format!(
            "{value:?} isn't a valid path segment"
        )));
    }
    let mut out = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            out.push(char::from(byte));
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    Ok(out)
}

struct Redacted;

impl fmt::Debug for Redacted {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("<redacted>")
    }
}

#[cfg(test)]
mod tests {
    use super::path_segment;

    #[test]
    fn path_segments_are_escaped() {
        let escaped = |v: &str| path_segment(v).expect("valid");
        assert_eq!(
            escaped("0b6c1f4e-1d2a-4c3b-9e8f-123456789abc"),
            "0b6c1f4e-1d2a-4c3b-9e8f-123456789abc"
        );
        assert_eq!(escaped("a/b?c#d"), "a%2Fb%3Fc%23d");
        assert_eq!(escaped("é"), "%C3%A9");
        for dot in ["", ".", ".."] {
            assert!(path_segment(dot).is_err(), "{dot:?}");
        }
    }
}
