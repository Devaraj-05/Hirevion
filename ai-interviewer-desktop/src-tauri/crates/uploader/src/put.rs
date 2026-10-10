//! The upload itself: a plain PUT of the plaintext to the write-only blob URL. No token and no
//! DPoP proof go there; the URL's signature is the only credential.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use reqwest::header::{CONTENT_LENGTH, HeaderName, HeaderValue};
use url::Url;

use crate::bandwidth::Bandwidth;

/// Why an upload URL or a PUT failed. `code()` is what the manifest and events record.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum PutError {
    /// Not HTTPS (plain HTTP is allowed only to the loopback address in debug builds).
    #[error("refused upload URL: {0}")]
    Insecure(String),
    /// A header the server asked for isn't a valid HTTP header.
    #[error("bad upload header: {0}")]
    BadHeader(String),
    /// The blob store answered with an error status.
    #[error("the blob store answered {0}")]
    Status(u16),
    /// No answer: DNS, TLS, connection or timeout.
    #[error("network error: {0}")]
    Network(String),
}

impl PutError {
    #[must_use]
    pub fn code(&self) -> String {
        match self {
            Self::Insecure(_) => "insecure-upload-url".into(),
            Self::BadHeader(_) => "bad-upload-header".into(),
            Self::Status(status) => format!("blob-{status}"),
            Self::Network(_) => "network".into(),
        }
    }
}

/// Accepts an upload URL only over HTTPS; plain HTTP only to `127.0.0.1`, `::1` or
/// `localhost` when `allow_insecure_loopback` (debug builds against a local blob emulator).
pub fn check_upload_url(raw: &str, allow_insecure_loopback: bool) -> Result<Url, PutError> {
    let url = Url::parse(raw).map_err(|e| PutError::Insecure(format!("{e}")))?;
    let loopback = matches!(
        url.host(),
        Some(url::Host::Domain("localhost"))
            | Some(url::Host::Ipv4(std::net::Ipv4Addr::LOCALHOST))
            | Some(url::Host::Ipv6(std::net::Ipv6Addr::LOCALHOST))
    );
    match url.scheme() {
        "https" => Ok(url),
        "http" if allow_insecure_loopback && loopback => Ok(url),
        scheme => Err(PutError::Insecure(format!(
            "{scheme}://{} is not HTTPS",
            url.host_str().unwrap_or("")
        ))),
    }
}

/// The client for blob uploads: rustls with the OS verifier, no redirects (a redirect could
/// send the video elsewhere) and a generous timeout for throttled uploads.
pub(crate) fn http_client() -> Result<reqwest::Client, String> {
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let verifier = rustls_platform_verifier::Verifier::new(provider.clone())
        .map_err(|e| format!("TLS verifier: {e}"))?;
    let tls = rustls::ClientConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .map_err(|e| format!("TLS versions: {e}"))?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(verifier))
        .with_no_client_auth();
    reqwest::Client::builder()
        .tls_backend_preconfigured(tls)
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(10))
        .read_timeout(Duration::from_secs(60))
        .timeout(Duration::from_secs(30 * 60))
        .build()
        .map_err(|e| format!("HTTP client: {e}"))
}

/// PUTs `body` to `url` with the server's `headers`, paced by `bandwidth` in `chunk`-byte
/// pieces. `Content-Length` is always sent: blob storage refuses chunked uploads.
pub(crate) async fn put(
    client: &reqwest::Client,
    url: Url,
    headers: &BTreeMap<String, String>,
    body: Vec<u8>,
    bandwidth: &Bandwidth,
    chunk: usize,
) -> Result<(), PutError> {
    let length = body.len();
    let mut request = client.put(url);
    for (name, value) in headers {
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| PutError::BadHeader(name.clone()))?;
        if name == CONTENT_LENGTH {
            continue;
        }
        let value =
            HeaderValue::from_str(value).map_err(|_| PutError::BadHeader(name.to_string()))?;
        request = request.header(name, value);
    }
    let chunk = chunk.max(1);
    let stream = futures_util::stream::unfold(
        (Bytes::from(body), bandwidth.clone()),
        move |(mut rest, bandwidth)| async move {
            if rest.is_empty() {
                return None;
            }
            let piece = rest.split_to(chunk.min(rest.len()));
            bandwidth.acquire(piece.len()).await;
            Some((Ok::<_, std::io::Error>(piece), (rest, bandwidth)))
        },
    );
    let response = request
        .header(CONTENT_LENGTH, length)
        .body(reqwest::Body::wrap_stream(stream))
        .send()
        .await
        .map_err(|e| PutError::Network(error_chain(&e)))?;
    let status = response.status();
    if status.is_success() {
        Ok(())
    } else {
        Err(PutError::Status(status.as_u16()))
    }
}

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn https_is_always_accepted() {
        assert!(check_upload_url("https://blob.example.test/c/b?sig=x", false).is_ok());
    }

    #[test]
    fn plain_http_only_to_loopback_and_only_when_allowed() {
        for url in [
            "http://127.0.0.1:10000/devstoreaccount1/b",
            "http://localhost:10000/b",
            "http://[::1]:10000/b",
        ] {
            assert!(check_upload_url(url, true).is_ok(), "{url}");
            assert!(check_upload_url(url, false).is_err(), "{url}");
        }
        assert!(check_upload_url("http://blob.example.test/b", true).is_err());
        assert!(check_upload_url("http://127.0.0.2/b", true).is_err());
        assert!(check_upload_url("http://localhost.example.test/b", true).is_err());
    }

    #[test]
    fn other_schemes_and_garbage_are_refused() {
        for url in ["ftp://blob.example.test/b", "file:///C:/b", "not a url"] {
            let error = check_upload_url(url, true).expect_err(url);
            assert_eq!(error.code(), "insecure-upload-url");
        }
    }
}
