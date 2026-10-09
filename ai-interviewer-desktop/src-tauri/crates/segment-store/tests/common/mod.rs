//! Shared helpers for the segment-store tests.
#![allow(dead_code)]

use std::path::{Path, PathBuf};

use hv_security::Vault;
use hv_segment_store::{Codec, Container, NewSegment, Recovery, SegmentStore, Track};

pub const INTERVIEW: &str = "0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6";

/// A fresh directory under the system temp dir, removed on drop.
pub struct TempDir(pub PathBuf);

impl TempDir {
    pub fn new() -> Self {
        let dir = std::env::temp_dir().join(format!("hv-store-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).expect("temp dir");
        Self(dir)
    }

    pub fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

/// Opens the store in `root/segments` with its keys in `root/vault`.
pub fn open(root: &Path) -> (SegmentStore, Recovery) {
    SegmentStore::open(root.join("segments"), Vault::new(root.join("vault"))).expect("store opens")
}

pub fn screen(seq: u64) -> NewSegment {
    NewSegment {
        interview_id: INTERVIEW.to_owned(),
        track: Track::Screen(1),
        seq,
        started_at_ms: 1_760_245_400_000 + i64::try_from(seq).expect("small") * 10_000,
        duration_ms: 10_000,
        container: Container::Mp4,
        codec: Codec::H264,
    }
}

/// Deterministic segment bytes that differ per `seq`.
pub fn payload(seq: u64, len: usize) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(len);
    let mut state = seq.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1;
    while bytes.len() < len {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        bytes.extend_from_slice(&state.to_le_bytes());
    }
    bytes.truncate(len);
    bytes
}
