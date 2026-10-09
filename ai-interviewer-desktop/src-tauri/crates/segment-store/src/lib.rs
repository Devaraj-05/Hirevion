//! The encrypted local queue of recording segments (PRD §51, master plan §6.11).
//!
//! - [`SegmentStore`] keeps every segment AES-256-GCM encrypted under a random per-interview
//!   key held in the DPAPI [`hv_security::Vault`], with a crash-safe SQLite manifest that walks
//!   each segment through [`SegmentState`] until the server acknowledges it.
//! - [`contract`] holds the track, container, codec and size rules of
//!   `docs/api/contracts/recordings.md`.
//! - [`webview`] turns the webview's camera and mic segment headers into a [`NewSegment`].

pub mod contract;
mod error;
mod file;
mod state;
mod store;
pub mod webview;

pub use contract::{Codec, Container, MAX_SEGMENT_BYTES, MAX_SEGMENT_MS, Track};
pub use error::StoreError;
pub use file::sha256_hex;
pub use state::SegmentState;
pub use store::{Counts, MANIFEST_FILE, NewSegment, Recovery, Segment, SegmentStore};
