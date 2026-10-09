use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

use hv_security::{Signer, dpop};
use reqwest::header::{ACCEPT, AUTHORIZATION, CONTENT_TYPE, HeaderValue, RETRY_AFTER};
use reqwest::{Method, Response};
use serde::Serialize;
use serde::de::DeserializeOwned;
use url::Url;

use crate::ApiError;
use crate::clock::{Clock, ClockSample, local_now_ms};

const DPOP: &str = "DPoP";
const DPOP_NONCE: &str = "DPoP-Nonce";
const USE_DPOP_NONCE: &str = "use-dpop-nonce";
const JSON: &str = "application/json";

/// The `User-Agent` every request sends: `HirevionInterview/<version> (Windows <build>; <arch>)`.
pub fn user_agent(app_version: &str, windows_build: &str, arch: &str) -> String {
    format!("HirevionInterview/{app_version} (Windows {windows_build}; {arch})")
}

/// Talks to the Hirevion API with DPoP-bound requests.
///
/// Call [`ApiClient::sync_clock`] at start-up: proofs are stamped in server time, and the server
/// refuses proofs more than 60 s off.
pub struct ApiClient {
    http: reqwest::Client,
    base: Url,
    signer: Arc<dyn Signer>,
    /// The latest `DPoP-Nonce` the server sent.
    nonce: Mutex<Option<String>>,
    clock: Clock,
}

impl std::fmt::Debug for ApiClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ApiClient")
            .field("base", &self.base.as_str())
            .field("clock", &self.clock.best())
            .finish_non_exhaustive()
    }
}

impl ApiClient {
    /// A client for the API at `base`, the `/api/v1` root (for example
    /// `https://api.hirevion.localhost/api/v1`). Request paths are relative to it.
    ///
    /// TLS is rustls with the operating system's verifier, so certificates trusted in the
    /// Windows store (the local Caddy CA, corporate CAs) are accepted.
    pub fn new(base: Url, signer: Arc<dyn Signer>, user_agent: String) -> Result<Self, ApiError> {
        if base.cannot_be_a_base() || !matches!(base.scheme(), "https" | "http") {
            return Err(ApiError::Security(format!(
                "the API base must be an http(s) URL, not {base}"
            )));
        }
        let mut base = base;
        base.set_query(None);
        base.set_fragment(None);
        if !base.path().ends_with('/') {
            let with_slash = format!("{}/", base.path());
            base.set_path(&with_slash);
        }
        let http = reqwest::Client::builder()
            .tls_backend_preconfigured(tls_config()?)
            .user_agent(user_agent)
            // A redirect would replay the token and proof somewhere else.
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|e| ApiError::Network(error_chain(&e)))?;
        Ok(Self {
            http,
            base,
            signer,
            nonce: Mutex::new(None),
            clock: Clock::default(),
        })
    }

    /// The API root, always ending in `/`.
    pub fn base(&self) -> &Url {
        &self.base
    }

    /// The device key that signs the proofs.
    pub fn signer(&self) -> &Arc<dyn Signer> {
        &self.signer
    }

    /// Measures the server time with `GET /time` and keeps the sample with the shortest round
    /// trip seen so far. Returns this measurement.
    ///
    /// This is the one request sent without a proof: its `iat` couldn't be trusted before the
    /// clock is known.
    pub async fn sync_clock(&self) -> Result<ClockSample, ApiError> {
        #[derive(serde::Deserialize)]
        struct ServerTime {
            received_at_ms: i64,
            sent_at_ms: i64,
        }

        let url = self.url("time")?;
        let started = Instant::now();
        let t0 = local_now_ms();
        let response = self
            .http
            .get(url)
            .header(ACCEPT, JSON)
            .send()
            .await
            .map_err(network)?;
        let t3 = t0.saturating_add(i64::try_from(started.elapsed().as_millis()).unwrap_or(0));
        if !response.status().is_success() {
            return Err(problem_from(response).await);
        }
        let bytes = response.bytes().await.map_err(network)?;
        let time: ServerTime = serde_json::from_slice(&bytes)
            .map_err(|e| ApiError::Decode(format!("GET /time: {e}")))?;
        let sample = ClockSample::from_timestamps(t0, time.received_at_ms, time.sent_at_ms, t3);
        self.clock.record(sample);
        Ok(sample)
    }

    /// The best clock sample so far, if the clock was synced.
    pub fn clock(&self) -> Option<ClockSample> {
        self.clock.best()
    }

    /// The server's time now, in milliseconds since the Unix epoch (local time until synced).
    pub fn server_now_ms(&self) -> i64 {
        local_now_ms().saturating_add(self.clock.best().map_or(0, |s| s.offset_ms))
    }

    /// Sends a request and decodes the JSON answer.
    ///
    /// `path` is relative to the API root and may carry a query string. `body` is sent as JSON.
    /// `token`, when given, is sent as `Authorization: DPoP <token>` and bound into the proof.
    pub async fn send<B: Serialize + ?Sized, T: DeserializeOwned>(
        &self,
        method: Method,
        path: &str,
        body: Option<&B>,
        token: Option<&str>,
    ) -> Result<T, ApiError> {
        let response = self.execute(method, path, body, token).await?;
        let bytes = response.bytes().await.map_err(network)?;
        serde_json::from_slice(&bytes).map_err(|e| ApiError::Decode(format!("{path}: {e}")))
    }

    /// Sends a request whose answer has no body we need (`202`, `204`).
    pub async fn send_no_content<B: Serialize + ?Sized>(
        &self,
        method: Method,
        path: &str,
        body: Option<&B>,
        token: Option<&str>,
    ) -> Result<(), ApiError> {
        self.execute(method, path, body, token).await.map(drop)
    }

    /// Resolves `path` against the API root, refusing anything that would leave it.
    pub fn url(&self, path: &str) -> Result<Url, ApiError> {
        let leaves = |why: &str| ApiError::Security(format!("refused path {path:?}: {why}"));
        if path.starts_with(['/', '\\']) || path.contains("://") {
            return Err(leaves("paths are relative to the API root"));
        }
        let url = self.base.join(path).map_err(|e| leaves(&e.to_string()))?;
        if url.origin() != self.base.origin() || !url.path().starts_with(self.base.path()) {
            return Err(leaves("it resolves outside the API root"));
        }
        Ok(url)
    }

    async fn execute<B: Serialize + ?Sized>(
        &self,
        method: Method,
        path: &str,
        body: Option<&B>,
        token: Option<&str>,
    ) -> Result<Response, ApiError> {
        let url = self.url(path)?;
        let body = body
            .map(serde_json::to_vec)
            .transpose()
            .map_err(|e| ApiError::Decode(format!("request body for {path}: {e}")))?;
        let authorization = token
            .map(|token| {
                let mut value = HeaderValue::from_str(&format!("DPoP {token}"))
                    .map_err(|_| ApiError::Security("the token isn't a valid header".into()))?;
                value.set_sensitive(true);
                Ok::<_, ApiError>(value)
            })
            .transpose()?;

        let mut retried = false;
        loop {
            let nonce = self
                .nonce
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .clone();
            let proof = dpop::proof(
                self.signer.as_ref(),
                method.as_str(),
                url.as_str(),
                token,
                nonce.as_deref(),
                self.server_now_ms().div_euclid(1000),
            )?;
            let mut request = self
                .http
                .request(method.clone(), url.clone())
                .header(DPOP, proof)
                .header(ACCEPT, JSON);
            if let Some(authorization) = &authorization {
                request = request.header(AUTHORIZATION, authorization.clone());
            }
            if let Some(body) = &body {
                request = request.header(CONTENT_TYPE, JSON).body(body.clone());
            }
            let response = request.send().await.map_err(network)?;

            // The server may hand out a fresh nonce on any answer; keep the latest.
            let fresh_nonce = response
                .headers()
                .get(DPOP_NONCE)
                .and_then(|v| v.to_str().ok())
                .map(str::to_owned);
            if let Some(fresh) = &fresh_nonce {
                *self.nonce.lock().unwrap_or_else(PoisonError::into_inner) = Some(fresh.clone());
            }
            if response.status().is_success() {
                return Ok(response);
            }
            let error = problem_from(response).await;
            if !retried && fresh_nonce.is_some() && error.is_problem(USE_DPOP_NONCE) {
                retried = true;
                continue;
            }
            return Err(error);
        }
    }
}

/// rustls with the ring provider and the OS certificate verifier.
fn tls_config() -> Result<rustls::ClientConfig, ApiError> {
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let verifier = rustls_platform_verifier::Verifier::new(provider.clone())
        .map_err(|e| ApiError::Security(format!("TLS verifier: {e}")))?;
    Ok(rustls::ClientConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .map_err(|e| ApiError::Security(format!("TLS versions: {e}")))?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(verifier))
        .with_no_client_auth())
}

/// Turns an error answer into [`ApiError::Problem`].
async fn problem_from(response: Response) -> ApiError {
    let status = response.status().as_u16();
    let retry_after = response
        .headers()
        .get(RETRY_AFTER)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.trim().parse::<u64>().ok());
    let bytes = match response.bytes().await {
        Ok(bytes) => bytes,
        Err(error) => return network(error),
    };
    let body = serde_json::from_slice::<serde_json::Value>(&bytes).unwrap_or_else(|_| {
        if bytes.is_empty() {
            serde_json::Value::Null
        } else {
            serde_json::Value::String(String::from_utf8_lossy(&bytes).into_owned())
        }
    });
    let code = body
        .get("code")
        .and_then(serde_json::Value::as_str)
        .map_or_else(|| format!("http-{status}"), str::to_owned);
    let detail = body
        .get("detail")
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned);
    ApiError::Problem {
        status,
        code,
        detail,
        retry_after,
        body,
    }
}

fn network(error: reqwest::Error) -> ApiError {
    ApiError::Network(error_chain(&error))
}

/// The error and its sources, joined: reqwest's own message rarely says what went wrong.
fn error_chain(error: &dyn std::error::Error) -> String {
    let mut message = error.to_string();
    let mut source = error.source();
    while let Some(cause) = source {
        message.push_str(": ");
        message.push_str(&cause.to_string());
        source = cause.source();
    }
    message
}
