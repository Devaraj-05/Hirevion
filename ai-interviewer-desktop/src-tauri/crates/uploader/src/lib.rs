//! Uploads recorded segments (`docs/api/contracts/recordings.md`, PRD §51).
//!
//! - [`Uploader`] takes segments from the [`hv_segment_store::SegmentStore`] one at a time,
//!   asks for a write-only URL (DPoP-bound, through [`hv_api_client::ApiClient`]), PUTs the
//!   plaintext there, asks for the hash-verified acknowledgement and only then deletes the
//!   local copy. [`Uploader::recover`] skips what the server already holds after a crash.
//! - Failures back off exponentially with jitter, capped at 30 s ([`backoff`]); a refused
//!   segment or track stops for good.
//! - [`Bandwidth`] caps the upload so live media keeps the link.

pub mod api;
pub mod backoff;
mod bandwidth;
mod put;
pub mod time;
mod uploader;

pub use bandwidth::{Bandwidth, TokenBucket};
pub use put::{PutError, check_upload_url};
pub use uploader::{
    RecordingSession, RecoverySummary, TokenFuture, UploadError, UploadEvent, Uploader,
    UploaderConfig,
};
