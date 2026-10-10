use hv_security::SecurityError;

use crate::SegmentState;

/// Everything the segment store can fail with.
#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    /// Reading or writing a segment file failed.
    #[error("segment storage I/O: {0}")]
    Io(#[from] std::io::Error),
    /// The SQLite manifest failed.
    #[error("segment manifest: {0}")]
    Manifest(String),
    /// The vault that holds the interview keys failed.
    #[error("recording key vault: {0}")]
    Vault(#[from] SecurityError),
    /// The interview's key isn't in the vault (another Windows user, or it was forgotten).
    #[error("no recording key for interview {0}")]
    KeyMissing(String),
    /// The file doesn't decrypt, or its contents don't match its header or manifest row.
    #[error("the segment file is corrupt or was tampered with: {0}")]
    Corrupt(String),
    /// The segment's file is gone.
    #[error("the segment file is missing: {0}")]
    FileMissing(String),
    /// The segment breaks `docs/api/contracts/recordings.md` (track, format, size, length).
    #[error("not allowed by the recordings contract: {0}")]
    Contract(String),
    /// A different segment is already stored under the same interview, track and seq.
    #[error("a different segment is already stored as {0}")]
    Conflict(String),
    /// No manifest row has this id.
    #[error("no segment {0}")]
    NotFound(i64),
    /// The state machine forbids this move.
    #[error("segment {id} can't go from {from} to {to}")]
    InvalidTransition {
        id: i64,
        from: SegmentState,
        to: SegmentState,
    },
}

impl From<rusqlite::Error> for StoreError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Manifest(error.to_string())
    }
}
