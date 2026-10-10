//! What the upload-drain screen shows after the interview (PRD §51, master plan §6.4
//! "Completion"): how much of the recording the server has acknowledged, and whether it is safe
//! to close the app.

use hv_segment_store::Counts;
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UploadProgress {
    /// Segments still to upload.
    pub pending: u64,
    pub pending_bytes: u64,
    /// Segments the server verified (their local copies are deleted).
    pub acknowledged: u64,
    /// Segments whose local file is gone: the server will see a gap.
    pub lost: u64,
    /// Segments the server refused for good.
    pub rejected: u64,
    /// 0 to 100; 100 only when `done`.
    pub percent: u8,
    /// Recording is still running, so more segments will follow.
    pub recording: bool,
    /// Nothing is left to upload and nothing more will be recorded: closing the app is safe.
    pub done: bool,
}

impl UploadProgress {
    /// From the store's totals for the interview. A segment that is lost or refused will never
    /// be acknowledged, so it counts as settled (the screen reports it); only `pending` and a
    /// recording that hasn't stopped keep the candidate waiting.
    pub fn from_counts(counts: &Counts, recording: bool) -> Self {
        let settled = counts.acknowledged + counts.lost + counts.rejected;
        let total = settled + counts.pending;
        let done = !recording && counts.pending == 0;
        let percent = if done || total == 0 {
            100
        } else {
            // Rounded down, so it never shows 100 while anything is pending.
            u8::try_from(settled * 100 / total).unwrap_or(100)
        };
        Self {
            pending: counts.pending,
            pending_bytes: counts.pending_bytes,
            acknowledged: counts.acknowledged,
            lost: counts.lost,
            rejected: counts.rejected,
            percent: if done { 100 } else { percent.min(99) },
            recording,
            done,
        }
    }

    /// An interview with nothing in the store (stub mode, or recording never started).
    pub fn nothing(recording: bool) -> Self {
        Self::from_counts(&Counts::default(), recording)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn counts(pending: u64, acknowledged: u64, lost: u64, rejected: u64) -> Counts {
        Counts {
            pending,
            pending_bytes: pending * 1_000,
            acknowledged,
            lost,
            rejected,
        }
    }

    #[test]
    fn nothing_stored_is_done() {
        let progress = UploadProgress::nothing(false);
        assert!(progress.done);
        assert_eq!(progress.percent, 100);
    }

    #[test]
    fn the_bar_follows_the_acknowledged_share() {
        let progress = UploadProgress::from_counts(&counts(3, 7, 0, 0), false);
        assert!(!progress.done);
        assert_eq!(progress.percent, 70);
        assert_eq!(progress.pending, 3);
        assert_eq!(progress.pending_bytes, 3_000);
    }

    #[test]
    fn it_never_shows_100_while_a_segment_is_pending() {
        let progress = UploadProgress::from_counts(&counts(1, 999, 0, 0), false);
        assert_eq!(progress.percent, 99);
        assert!(!progress.done);
    }

    #[test]
    fn nothing_pending_is_done_once_recording_has_stopped() {
        let progress = UploadProgress::from_counts(&counts(0, 12, 0, 0), false);
        assert!(progress.done);
        assert_eq!(progress.percent, 100);
    }

    #[test]
    fn it_is_not_done_while_recording_continues() {
        let progress = UploadProgress::from_counts(&counts(0, 12, 0, 0), true);
        assert!(!progress.done);
        assert!(progress.recording);
        assert_eq!(progress.percent, 99);
    }

    #[test]
    fn lost_and_refused_segments_do_not_hold_the_candidate_back() {
        let progress = UploadProgress::from_counts(&counts(0, 10, 2, 1), false);
        assert!(progress.done);
        assert_eq!((progress.lost, progress.rejected), (2, 1));
        // …but they are not hidden: the screen tells the candidate.
        assert_eq!(progress.acknowledged, 10);
    }

    #[test]
    fn lost_segments_count_as_settled_for_the_bar() {
        let progress = UploadProgress::from_counts(&counts(2, 6, 2, 0), false);
        assert_eq!(progress.percent, 80);
    }
}
