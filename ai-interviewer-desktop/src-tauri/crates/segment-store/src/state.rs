//! The life of a stored segment.

use std::fmt;
use std::str::FromStr;

use serde::Serialize;

/// Where a segment is on its way to the server.
///
/// ```text
/// captured → queued → uploading → uploaded → acknowledged → purged
///               ↑_________|___________|          (a retry, a 422 or a 404)
/// ```
///
/// Any pending state may jump to `acknowledged` (the server already has it), to `lost` (its
/// file vanished or doesn't decrypt) or to `rejected` (the server refuses it for good:
/// `segment-too-large`, `track-not-recorded`). `purged`, `lost` and `rejected` are final.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum SegmentState {
    /// Encrypted and durable on disk.
    Captured,
    /// Waiting for the uploader.
    Queued,
    /// An upload URL was issued and the upload is under way.
    Uploading,
    /// The blob was uploaded; the acknowledgement is outstanding.
    Uploaded,
    /// The server verified the hash. The local file may now be deleted.
    Acknowledged,
    /// The local file was deleted after the acknowledgement.
    Purged,
    /// The local file is missing or unreadable.
    Lost,
    /// The server refuses this segment for good.
    Rejected,
}

impl SegmentState {
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Captured => "captured",
            Self::Queued => "queued",
            Self::Uploading => "uploading",
            Self::Uploaded => "uploaded",
            Self::Acknowledged => "acknowledged",
            Self::Purged => "purged",
            Self::Lost => "lost",
            Self::Rejected => "rejected",
        }
    }

    /// Still needs the server: captured, queued, uploading or uploaded.
    #[must_use]
    pub fn is_pending(self) -> bool {
        matches!(
            self,
            Self::Captured | Self::Queued | Self::Uploading | Self::Uploaded
        )
    }

    /// Whether a segment may move from `self` to `to`.
    #[must_use]
    pub fn allows(self, to: Self) -> bool {
        use SegmentState::{
            Acknowledged, Captured, Lost, Purged, Queued, Rejected, Uploaded, Uploading,
        };
        match (self, to) {
            (from, Acknowledged | Lost | Rejected) if from.is_pending() => true,
            (Captured | Uploading | Uploaded, Queued)
            | (Queued, Uploading)
            | (Uploading, Uploaded)
            | (Acknowledged, Purged) => true,
            _ => false,
        }
    }
}

impl fmt::Display for SegmentState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for SegmentState {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        ALL.into_iter()
            .find(|state| state.as_str() == value)
            .ok_or_else(|| format!("unknown segment state {value:?}"))
    }
}

const ALL: [SegmentState; 8] = [
    SegmentState::Captured,
    SegmentState::Queued,
    SegmentState::Uploading,
    SegmentState::Uploaded,
    SegmentState::Acknowledged,
    SegmentState::Purged,
    SegmentState::Lost,
    SegmentState::Rejected,
];

#[cfg(test)]
mod tests {
    use super::SegmentState::*;
    use super::*;

    #[test]
    fn the_happy_path_is_allowed() {
        let path = [Captured, Queued, Uploading, Uploaded, Acknowledged, Purged];
        for pair in path.windows(2) {
            assert!(pair[0].allows(pair[1]), "{} -> {}", pair[0], pair[1]);
        }
    }

    #[test]
    fn retries_go_back_to_the_queue() {
        assert!(Uploading.allows(Queued));
        assert!(Uploaded.allows(Queued));
    }

    #[test]
    fn nothing_skips_ahead_or_leaves_a_final_state() {
        assert!(!Captured.allows(Uploading));
        assert!(!Captured.allows(Uploaded));
        assert!(!Queued.allows(Uploaded));
        assert!(!Captured.allows(Purged));
        assert!(!Uploaded.allows(Purged));
        for from in [Acknowledged, Purged, Lost, Rejected] {
            for to in ALL {
                let allowed = from == Acknowledged && to == Purged;
                assert_eq!(from.allows(to), allowed, "{from} -> {to}");
            }
        }
    }

    #[test]
    fn any_pending_state_can_be_acknowledged() {
        for from in [Captured, Queued, Uploading, Uploaded] {
            assert!(from.allows(Acknowledged), "{from}");
            assert!(from.allows(Lost), "{from}");
            assert!(from.allows(Rejected), "{from}");
        }
    }

    #[test]
    fn names_round_trip() {
        for state in ALL {
            assert_eq!(state.as_str().parse::<SegmentState>(), Ok(state));
        }
        assert!("done".parse::<SegmentState>().is_err());
    }
}
