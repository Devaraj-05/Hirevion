//! Evidence pictures the server asked for (`proctoring.md`, "Changes" 2026-10-11): a
//! write-only slot from `POST /proctoring/evidence-uploads` that names the `request_id` (the
//! blob is then already linked to the event), then a PUT of the bytes. One attempt per call;
//! the caller retries what [`EvidenceError::is_final`] says may work.

use std::collections::BTreeMap;

use hv_api_client::{ApiClient, ApiError, Method};
use hv_segment_store::sha256_hex;
use serde::{Deserialize, Serialize};

use crate::bandwidth::Bandwidth;
use crate::put::{self, PutError};

/// The server's limit for one picture (2 MiB).
pub const MAX_EVIDENCE_BYTES: usize = 2 * 1024 * 1024;
/// Pictures are small; one piece is enough.
const CHUNK: usize = 256 * 1024;

/// What the picture answers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EvidenceAnswer<'a> {
    pub proctor_session_id: &'a str,
    pub request_id: &'a str,
    /// `screen` or `camera`: the kind the server asked for.
    pub kind: &'a str,
    pub content_type: &'a str,
}

/// Why an answer failed.
#[derive(Debug, thiserror::Error)]
pub enum EvidenceError {
    /// Empty, or over [`MAX_EVIDENCE_BYTES`]: never sent.
    #[error("the picture can't be sent: {0}")]
    Invalid(&'static str),
    #[error(transparent)]
    Api(#[from] ApiError),
    #[error(transparent)]
    Put(#[from] PutError),
    /// The blob client couldn't be built.
    #[error("upload setup: {0}")]
    Setup(String),
}

impl EvidenceError {
    /// A stable code: the problem's code, `blob-<status>`, `network`, `invalid-evidence`.
    #[must_use]
    pub fn code(&self) -> String {
        match self {
            Self::Invalid(_) => "invalid-evidence".into(),
            Self::Api(error) => error.code().to_owned(),
            Self::Put(error) => error.code(),
            Self::Setup(_) => "upload-setup".into(),
        }
    }

    /// Whether trying again can't help: the server refused the request for good (unknown or
    /// foreign request, already answered with another picture, a closed session, a bad body),
    /// or the picture or the URL is unusable. Network failures, `5xx`, `429` and a rejected
    /// session token (replaced by the caller) may work next time.
    #[must_use]
    pub fn is_final(&self) -> bool {
        match self {
            Self::Invalid(_) | Self::Setup(_) => true,
            Self::Api(error) => {
                !error.is_problem("token-invalid")
                    && error
                        .status()
                        .is_some_and(|status| (400..500).contains(&status) && status != 429)
            }
            Self::Put(error) => matches!(error, PutError::Insecure(_) | PutError::BadHeader(_)),
        }
    }
}

/// The plain HTTP client for blob PUTs (no token, no proof, no redirects).
#[derive(Debug, Clone)]
pub struct BlobClient {
    http: reqwest::Client,
    allow_insecure_loopback: bool,
}

impl BlobClient {
    /// `allow_insecure_loopback`: plain HTTP to the loopback address (debug builds against a
    /// local blob emulator); everything else must be HTTPS.
    pub fn new(allow_insecure_loopback: bool) -> Result<Self, EvidenceError> {
        Ok(Self {
            http: put::http_client().map_err(EvidenceError::Setup)?,
            allow_insecure_loopback,
        })
    }
}

#[derive(Serialize)]
struct SlotRequest<'a> {
    proctor_session_id: &'a str,
    kind: &'a str,
    request_id: &'a str,
    content_type: &'a str,
    bytes: usize,
    sha256: String,
}

#[derive(Deserialize)]
struct Slot {
    upload_url: String,
    blob_path: String,
    #[serde(default)]
    headers: BTreeMap<String, String>,
}

/// Asks for the slot and PUTs `bytes` there; returns the blob's path. Asking again with the
/// same picture gets the same blob, so a retry after a failed PUT is safe.
pub async fn upload_evidence(
    api: &ApiClient,
    blob: &BlobClient,
    session_token: &str,
    answer: &EvidenceAnswer<'_>,
    bytes: Vec<u8>,
) -> Result<String, EvidenceError> {
    if bytes.is_empty() {
        return Err(EvidenceError::Invalid("empty"));
    }
    if bytes.len() > MAX_EVIDENCE_BYTES {
        return Err(EvidenceError::Invalid("too large"));
    }
    let request = SlotRequest {
        proctor_session_id: answer.proctor_session_id,
        kind: answer.kind,
        request_id: answer.request_id,
        content_type: answer.content_type,
        bytes: bytes.len(),
        sha256: sha256_hex(&bytes),
    };
    let slot: Slot = api
        .send(
            Method::POST,
            "proctoring/evidence-uploads",
            Some(&request),
            Some(session_token),
        )
        .await?;
    let url = put::check_upload_url(&slot.upload_url, blob.allow_insecure_loopback)?;
    put::put(
        &blob.http,
        url,
        &slot.headers,
        bytes,
        &Bandwidth::unlimited(),
        CHUNK,
    )
    .await?;
    Ok(slot.blob_path)
}
