//! Shared helpers for the wiremock tests.
#![allow(dead_code)]

use std::path::PathBuf;
use std::sync::Arc;

use hv_api_client::{ApiClient, Url};
use hv_security::{SoftwareKey, dpop};
use wiremock::{Match, MockServer, Request};

pub const USER_AGENT: &str = "HirevionInterview/1.4.0 (Windows 26200; x64)";

pub async fn server_and_client() -> (MockServer, ApiClient) {
    let server = MockServer::start().await;
    let client = client_for(&server);
    (server, client)
}

pub fn client_for(server: &MockServer) -> ApiClient {
    let base = Url::parse(&format!("{}/api/v1", server.uri())).expect("base url");
    ApiClient::new(base, Arc::new(SoftwareKey::generate()), USER_AGENT.into()).expect("client")
}

/// The verified DPoP proof of a received request.
pub fn proof_of(request: &Request) -> dpop::VerifiedProof {
    let header = request
        .headers
        .get("DPoP")
        .expect("DPoP header")
        .to_str()
        .expect("ascii");
    dpop::verify(header).expect("proof verifies")
}

/// Matches requests whose DPoP proof carries this nonce (or none).
pub struct ProofNonce(pub Option<&'static str>);

impl Match for ProofNonce {
    fn matches(&self, request: &Request) -> bool {
        request
            .headers
            .get("DPoP")
            .and_then(|h| h.to_str().ok())
            .and_then(|h| dpop::verify(h).ok())
            .is_some_and(|p| p.claims.nonce.as_deref() == self.0)
    }
}

pub fn problem(status: u16, code: &str) -> serde_json::Value {
    serde_json::json!({
        "type": format!("https://hirevion.example.test/problems/{code}"),
        "title": "Problem",
        "status": status,
        "detail": format!("{code} happened"),
        "code": code,
    })
}

/// A fresh directory under the system temp dir, removed on drop.
pub struct TempDir(pub PathBuf);

impl TempDir {
    pub fn new() -> Self {
        Self(std::env::temp_dir().join(format!("hv-api-test-{}", uuid::Uuid::new_v4())))
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
