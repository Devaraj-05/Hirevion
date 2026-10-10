//! The three DPoP-bound calls of `docs/api/contracts/recordings.md`.

use std::collections::BTreeMap;

use hv_api_client::{ApiClient, ApiError, Method};
use hv_segment_store::Segment;
use serde::{Deserialize, Serialize};

use crate::time;

/// `200` of `POST /recordings/segments`.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct UploadTicket {
    pub segment_id: String,
    /// Write-only, one blob, about 15 minutes.
    pub upload_url: String,
    /// Headers the PUT must carry (`x-ms-blob-type`, `Content-Type`).
    #[serde(default)]
    pub headers: BTreeMap<String, String>,
    /// When `upload_url` stops working (RFC 3339).
    #[serde(default)]
    pub expires_at: Option<String>,
}

/// One track in the recovery listing.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
pub struct TrackProgress {
    /// Every seq up to this one is acknowledged, except `missing`. Absent (or negative) when
    /// nothing is acknowledged yet.
    #[serde(default)]
    pub acknowledged_through: Option<i64>,
    #[serde(default)]
    pub missing: Vec<u64>,
}

impl TrackProgress {
    /// Whether the server already acknowledged `seq`.
    #[must_use]
    pub fn has(&self, seq: u64) -> bool {
        self.acknowledged_through
            .and_then(|through| u64::try_from(through).ok())
            .is_some_and(|through| seq <= through && !self.missing.contains(&seq))
    }
}

/// `200` of `GET /recordings/interviews/{id}/segments`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
pub struct Listing {
    #[serde(default)]
    pub tracks: BTreeMap<String, TrackProgress>,
}

#[derive(Serialize)]
struct UrlRequest<'a> {
    interview_id: &'a str,
    track: String,
    seq: u64,
    started_at: String,
    duration_ms: u32,
    bytes: u64,
    sha256: &'a str,
    container: &'static str,
    codec: &'static str,
}

/// `POST /recordings/segments`.
pub async fn request_upload(
    api: &ApiClient,
    token: &str,
    segment: &Segment,
) -> Result<UploadTicket, ApiError> {
    let body = UrlRequest {
        interview_id: &segment.interview_id,
        track: segment.track.to_string(),
        seq: segment.seq,
        started_at: time::format_ms(segment.started_at_ms),
        duration_ms: segment.duration_ms,
        bytes: segment.bytes,
        sha256: &segment.sha256,
        container: segment.container.as_str(),
        codec: segment.codec.as_str(),
    };
    let ticket: UploadTicket = api
        .send(
            Method::POST,
            "recordings/segments",
            Some(&body),
            Some(token),
        )
        .await?;
    check_segment_id(&ticket.segment_id)?;
    Ok(ticket)
}

/// `POST /recordings/segments/{segment_id}/ack`.
pub async fn acknowledge(
    api: &ApiClient,
    token: &str,
    segment_id: &str,
    sha256: &str,
) -> Result<(), ApiError> {
    #[derive(Deserialize)]
    struct Answer {
        status: String,
    }
    check_segment_id(segment_id)?;
    let answer: Answer = api
        .send(
            Method::POST,
            &format!("recordings/segments/{segment_id}/ack"),
            Some(&serde_json::json!({ "sha256": sha256 })),
            Some(token),
        )
        .await?;
    if answer.status == "acknowledged" {
        Ok(())
    } else {
        Err(ApiError::Decode(format!(
            "ack answered status {:?}",
            answer.status
        )))
    }
}

/// `GET /recordings/interviews/{interview_id}/segments`.
pub async fn listing(
    api: &ApiClient,
    token: &str,
    interview_id: &str,
) -> Result<Listing, ApiError> {
    api.send::<(), Listing>(
        Method::GET,
        &format!("recordings/interviews/{interview_id}/segments"),
        None,
        Some(token),
    )
    .await
}

/// Segment ids become a path segment: only plain tokens are accepted.
fn check_segment_id(segment_id: &str) -> Result<(), ApiError> {
    let plain = (1..=128).contains(&segment_id.len())
        && segment_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'));
    if plain {
        Ok(())
    } else {
        Err(ApiError::Decode(format!(
            "segment id {segment_id:?} isn't a plain token"
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn progress_counts_through_except_missing() {
        let progress: TrackProgress =
            serde_json::from_str(r#"{ "acknowledged_through": 16, "missing": [9] }"#)
                .expect("json");
        assert!(progress.has(0));
        assert!(progress.has(16));
        assert!(!progress.has(9));
        assert!(!progress.has(17));
    }

    #[test]
    fn nothing_acknowledged_yet() {
        for json in [
            r#"{}"#,
            r#"{ "acknowledged_through": null }"#,
            r#"{ "acknowledged_through": -1, "missing": [] }"#,
        ] {
            let progress: TrackProgress = serde_json::from_str(json).expect("json");
            assert!(!progress.has(0), "{json}");
        }
    }

    #[test]
    fn segment_ids_must_be_plain_tokens() {
        assert!(check_segment_id("0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6").is_ok());
        for bad in ["", "../ack", "a/b", "a?b", &"x".repeat(129)] {
            assert!(check_segment_id(bad).is_err(), "{bad}");
        }
    }
}
