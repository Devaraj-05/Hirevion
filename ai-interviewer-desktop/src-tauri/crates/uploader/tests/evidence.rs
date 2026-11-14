//! Answering a snapshot request (`proctoring.md`, "Changes" 2026-10-11): a write-only slot
//! from `POST /proctoring/evidence-uploads` with the `request_id`, then a PUT of the picture.

use std::sync::Arc;

use hv_api_client::{ApiClient, Url};
use hv_security::SoftwareKey;
use hv_segment_store::sha256_hex;
use hv_uploader::{BlobClient, EvidenceAnswer, MAX_EVIDENCE_BYTES, upload_evidence};
use serde_json::{Value, json};
use wiremock::matchers::{body_partial_json, header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

const SESSION: &str = "0b0e6f9c-0000-4000-8000-00000000c0de";
const REQUEST: &str = "0b0e6f9c-0000-4000-8000-000000000001";
const TOKEN: &str = "interview-session-token";

fn client(server: &MockServer) -> ApiClient {
    let base = Url::parse(&format!("{}/api/v1", server.uri())).expect("base");
    ApiClient::new(
        base,
        Arc::new(SoftwareKey::generate()),
        "HirevionInterview/1.4.0 (Windows 26200; x64)".into(),
    )
    .expect("client")
}

fn answer() -> EvidenceAnswer<'static> {
    EvidenceAnswer {
        proctor_session_id: SESSION,
        request_id: REQUEST,
        kind: "screen",
        content_type: "image/jpeg",
    }
}

/// A tiny stand-in for a JPEG: the upload never looks inside.
fn picture() -> Vec<u8> {
    let mut bytes = vec![0xFF, 0xD8, 0xFF, 0xE0];
    bytes.extend((0..200u8).collect::<Vec<_>>());
    bytes.extend([0xFF, 0xD9]);
    bytes
}

async fn slot(server: &MockServer) {
    let bytes = picture();
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/evidence-uploads"))
        .and(header("authorization", format!("DPoP {TOKEN}").as_str()))
        .and(body_partial_json(json!({
            "proctor_session_id": SESSION,
            "request_id": REQUEST,
            "kind": "screen",
            "content_type": "image/jpeg",
            "bytes": bytes.len(),
            "sha256": sha256_hex(&bytes),
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "upload_url": format!("{}/blob/org/interviews/iv/evidence/0b0e6f9c-screen.jpg?sig=test-only", server.uri()),
            "blob_path": "org/interviews/iv/evidence/0b0e6f9c-screen.jpg",
            "headers": { "x-ms-blob-type": "BlockBlob" }
        })))
        .mount(server)
        .await;
}

#[tokio::test]
async fn a_picture_goes_to_the_slot_the_server_gives_for_the_request() {
    let server = MockServer::start().await;
    slot(&server).await;
    Mock::given(method("PUT"))
        .and(path("/blob/org/interviews/iv/evidence/0b0e6f9c-screen.jpg"))
        .and(header("x-ms-blob-type", "BlockBlob"))
        .respond_with(ResponseTemplate::new(201))
        .expect(1)
        .mount(&server)
        .await;
    let blob = BlobClient::new(true).expect("blob client");
    let path = upload_evidence(&client(&server), &blob, TOKEN, &answer(), picture())
        .await
        .expect("uploaded");
    assert_eq!(path, "org/interviews/iv/evidence/0b0e6f9c-screen.jpg");

    let put = server
        .received_requests()
        .await
        .expect("requests")
        .into_iter()
        .find(|request| request.method.as_str() == "PUT")
        .expect("a PUT");
    assert_eq!(put.body, picture());
    // The blob store gets no token and no proof: the URL's signature is the credential.
    assert!(put.headers.get("authorization").is_none());
    assert!(put.headers.get("dpop").is_none());
}

#[tokio::test]
async fn refusals_are_final_and_failures_are_retryable() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/api/v1/proctoring/evidence-uploads"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({
            "type": "about:blank", "status": 404, "code": "snapshot-request-not-found",
            "title": "No such snapshot request"
        })))
        .mount(&server)
        .await;
    let blob = BlobClient::new(true).expect("blob client");
    let error = upload_evidence(&client(&server), &blob, TOKEN, &answer(), picture())
        .await
        .expect_err("refused");
    assert_eq!(error.code(), "snapshot-request-not-found");
    assert!(error.is_final());

    let server = MockServer::start().await;
    slot(&server).await;
    Mock::given(method("PUT"))
        .respond_with(ResponseTemplate::new(503))
        .mount(&server)
        .await;
    let error = upload_evidence(&client(&server), &blob, TOKEN, &answer(), picture())
        .await
        .expect_err("the blob store failed");
    assert_eq!(error.code(), "blob-503");
    assert!(!error.is_final(), "a new slot and PUT may work");
}

#[tokio::test]
async fn an_empty_or_oversized_picture_never_leaves_the_app() {
    let server = MockServer::start().await;
    let blob = BlobClient::new(true).expect("blob client");
    for bytes in [Vec::new(), vec![0u8; MAX_EVIDENCE_BYTES + 1]] {
        let error = upload_evidence(&client(&server), &blob, TOKEN, &answer(), bytes)
            .await
            .expect_err("refused locally");
        assert_eq!(error.code(), "invalid-evidence");
        assert!(error.is_final());
    }
    let requests: Vec<Value> = server
        .received_requests()
        .await
        .expect("requests")
        .iter()
        .map(|request| json!(request.url.path()))
        .collect();
    assert!(requests.is_empty(), "{requests:?}");
}

#[tokio::test]
async fn an_insecure_upload_url_is_refused() {
    let server = MockServer::start().await;
    slot(&server).await;
    // Release builds take HTTPS only; the mock server is plain HTTP.
    let blob = BlobClient::new(false).expect("blob client");
    let error = upload_evidence(&client(&server), &blob, TOKEN, &answer(), picture())
        .await
        .expect_err("refused");
    assert_eq!(error.code(), "insecure-upload-url");
    assert!(error.is_final());
}
