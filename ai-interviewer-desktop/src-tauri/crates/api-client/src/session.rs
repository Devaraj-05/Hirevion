use std::time::{Duration, Instant};

use hv_security::Vault;
use tokio::sync::Mutex;

use crate::auth::{self, LoginOutcome, LoginRequest, Me, OtpVerify, SessionToken};
use crate::{ApiClient, ApiError};

/// The vault entry that holds the refresh token.
pub const REFRESH_TOKEN_KEY: &str = "refresh-token";

/// Refresh the access token when less than this is left.
const REFRESH_MARGIN: Duration = Duration::from_secs(60);

/// The candidate's session.
///
/// - The access token and its expiry stay in memory.
/// - The refresh token lives only in the [`Vault`] (under [`REFRESH_TOKEN_KEY`]), so a restart
///   resumes the session.
/// - [`SessionManager::access_token`] refreshes when less than 60 s remain and stores the
///   rotated refresh token. Refreshes are serialised: a refresh token is never sent twice
///   (that would revoke the whole family).
/// - A `refresh-reused` or `refresh-invalid` answer ends the session.
///
/// The [`LoginOutcome`]s returned here still carry the tokens: callers must not pass them on to
/// the webview.
pub struct SessionManager {
    api: ApiClient,
    vault: Vault,
    access: Mutex<Option<AccessToken>>,
}

struct AccessToken {
    token: String,
    expires_at: Instant,
}

impl std::fmt::Debug for SessionManager {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SessionManager")
            .field("api", &self.api)
            .field("vault", &self.vault)
            .finish_non_exhaustive()
    }
}

impl SessionManager {
    /// A session manager with no session in memory (a saved refresh token is picked up by the
    /// first [`SessionManager::access_token`]).
    pub fn new(api: ApiClient, vault: Vault) -> Self {
        Self {
            api,
            vault,
            access: Mutex::new(None),
        }
    }

    /// The API client, for calls that don't need the candidate's access token.
    pub fn api(&self) -> &ApiClient {
        &self.api
    }

    /// Whether a refresh token is saved, i.e. a session can probably be resumed.
    pub fn has_saved_session(&self) -> bool {
        matches!(self.vault.get(REFRESH_TOKEN_KEY), Ok(Some(_)))
    }

    /// Signs in. On `ok` the tokens are kept; on `otp_required` nothing is stored yet.
    pub async fn sign_in(&self, request: &LoginRequest) -> Result<LoginOutcome, ApiError> {
        let mut access = self.access.lock().await;
        let outcome = auth::login(&self.api, request).await?;
        self.keep(&mut access, &outcome)?;
        Ok(outcome)
    }

    /// Verifies the one-time code and keeps the tokens.
    pub async fn verify_code(&self, request: &OtpVerify) -> Result<LoginOutcome, ApiError> {
        let mut access = self.access.lock().await;
        let outcome = auth::verify_otp(&self.api, request).await?;
        self.keep(&mut access, &outcome)?;
        Ok(outcome)
    }

    /// Sends the one-time code again.
    pub async fn resend_code(&self, challenge_id: &str) -> Result<(), ApiError> {
        auth::resend_otp(&self.api, challenge_id).await
    }

    /// A valid access token, refreshed first when less than 60 s remain.
    ///
    /// [`ApiError::SignedOut`] when there is no session.
    pub async fn access_token(&self) -> Result<String, ApiError> {
        let mut access = self.access.lock().await;
        self.fresh_token(&mut access).await
    }

    /// The candidate, organisation and interview list.
    pub async fn me(&self) -> Result<Me, ApiError> {
        self.authorized(|token| async move { auth::me(&self.api, &token).await })
            .await
    }

    /// An interview-session token for one interview.
    pub async fn session_token(&self, interview_id: &str) -> Result<SessionToken, ApiError> {
        self.authorized(|token| async move {
            auth::session_token(&self.api, &token, interview_id).await
        })
        .await
    }

    /// Runs `call` with a valid access token. The server answers `401 token-invalid` for an
    /// expired or revoked token (contract candidate-auth): that forces one refresh and one
    /// retry, and a second refusal ends the session.
    async fn authorized<T, F, Fut>(&self, call: F) -> Result<T, ApiError>
    where
        F: Fn(String) -> Fut,
        Fut: std::future::Future<Output = Result<T, ApiError>>,
    {
        let token = self.access_token().await?;
        match call(token).await {
            Err(error) if error.is_problem("token-invalid") => {}
            other => return other,
        }
        let token = {
            let mut access = self.access.lock().await;
            // Forget the rejected token, so the next one comes from the refresh token.
            *access = None;
            self.fresh_token(&mut access).await?
        };
        match call(token).await {
            Err(error) if error.is_problem("token-invalid") => {
                let mut access = self.access.lock().await;
                self.clear(&mut access);
                Err(ApiError::SignedOut)
            }
            other => other,
        }
    }

    /// Signs out: revokes the refresh family on the server, then forgets the tokens.
    ///
    /// The local session is always cleared, even when this returns an error (the server
    /// couldn't be told). Having no session to end is not an error.
    pub async fn sign_out(&self) -> Result<(), ApiError> {
        let mut access = self.access.lock().await;
        let remote = match self.fresh_token(&mut access).await {
            Ok(token) => auth::logout(&self.api, &token).await,
            Err(error) if ends_session(&error) || matches!(error, ApiError::SignedOut) => Ok(()),
            Err(error) => Err(error),
        };
        *access = None;
        let local = self.vault.delete(REFRESH_TOKEN_KEY).map_err(ApiError::from);
        remote.and(local)
    }

    async fn fresh_token(&self, access: &mut Option<AccessToken>) -> Result<String, ApiError> {
        if let Some(current) = access.as_ref()
            && current.expires_at > Instant::now() + REFRESH_MARGIN
        {
            return Ok(current.token.clone());
        }

        let Some(saved) = self.vault.get(REFRESH_TOKEN_KEY)? else {
            *access = None;
            return Err(ApiError::SignedOut);
        };
        let Ok(refresh_token) = String::from_utf8(saved) else {
            self.clear(access);
            return Err(ApiError::SignedOut);
        };

        match auth::refresh(&self.api, &refresh_token).await {
            Ok(pair) => {
                self.store(
                    access,
                    &pair.access_token,
                    pair.expires_in,
                    &pair.refresh_token,
                )?;
                Ok(pair.access_token)
            }
            Err(error) if ends_session(&error) => {
                self.clear(access);
                Err(error)
            }
            // A failed refresh (network, update required) doesn't end the session; the current
            // token is still usable while it hasn't expired.
            Err(error) => match access.as_ref() {
                Some(current) if current.expires_at > Instant::now() => Ok(current.token.clone()),
                _ => Err(error),
            },
        }
    }

    fn keep(
        &self,
        access: &mut Option<AccessToken>,
        outcome: &LoginOutcome,
    ) -> Result<(), ApiError> {
        match outcome {
            LoginOutcome::Ok(signed_in) => self.store(
                access,
                &signed_in.access_token,
                signed_in.expires_in,
                &signed_in.refresh_token,
            ),
            LoginOutcome::OtpRequired(_) => Ok(()),
        }
    }

    fn store(
        &self,
        access: &mut Option<AccessToken>,
        access_token: &str,
        expires_in: u64,
        refresh_token: &str,
    ) -> Result<(), ApiError> {
        *access = Some(AccessToken {
            token: access_token.to_owned(),
            // Capped at a day so a bogus value can't overflow the Instant.
            expires_at: Instant::now() + Duration::from_secs(expires_in.min(86_400)),
        });
        // The previous refresh token is dead now: the new one must reach the vault.
        self.vault
            .put(REFRESH_TOKEN_KEY, refresh_token.as_bytes())
            .map_err(ApiError::from)
    }

    fn clear(&self, access: &mut Option<AccessToken>) {
        *access = None;
        // Best effort: a vault entry we can't delete is refused by the server anyway.
        let _ = self.vault.delete(REFRESH_TOKEN_KEY);
    }
}

/// Refresh answers that mean the session is over and the candidate must sign in again.
fn ends_session(error: &ApiError) -> bool {
    error.is_problem("refresh-reused") || error.is_problem("refresh-invalid")
}
