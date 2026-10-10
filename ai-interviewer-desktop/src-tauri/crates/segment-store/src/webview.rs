//! Camera and microphone segments arrive from the webview as raw IPC bytes with their
//! description in headers (`recording_store_segment`). The webview is untrusted: it may
//! only describe camera and mic segments, and never chooses the interview.

use crate::contract::{MAX_SEGMENT_MS, check_format};
use crate::{Codec, Container, NewSegment, StoreError, Track};

pub const HEADER_TRACK: &str = "x-hv-track";
pub const HEADER_SEQ: &str = "x-hv-seq";
pub const HEADER_STARTED_AT_MS: &str = "x-hv-started-at-ms";
pub const HEADER_DURATION_MS: &str = "x-hv-duration-ms";
pub const HEADER_CONTAINER: &str = "x-hv-container";
pub const HEADER_CODEC: &str = "x-hv-codec";

/// Builds a [`NewSegment`] for the interview being recorded (which Rust knows) from the
/// webview's headers. `header` looks a header up by its lower-case name.
pub fn segment_from_headers(
    interview_id: &str,
    header: impl Fn(&str) -> Option<String>,
) -> Result<NewSegment, StoreError> {
    let get = |name: &str| {
        header(name)
            .map(|value| value.trim().to_owned())
            .filter(|value| !value.is_empty())
            .ok_or_else(|| StoreError::Contract(format!("missing header {name}")))
    };
    let number = |name: &str| -> Result<i64, StoreError> {
        get(name)?
            .parse::<i64>()
            .map_err(|_| StoreError::Contract(format!("{name} isn't a whole number")))
    };

    let track: Track = get(HEADER_TRACK)?.parse().map_err(StoreError::Contract)?;
    if track.is_screen() {
        return Err(StoreError::Contract(
            "screen tracks come from the native recorder".into(),
        ));
    }
    let seq = u64::try_from(number(HEADER_SEQ)?)
        .map_err(|_| StoreError::Contract("seq starts at 0".into()))?;
    let started_at_ms = number(HEADER_STARTED_AT_MS)?;
    let duration_ms = u32::try_from(number(HEADER_DURATION_MS)?)
        .ok()
        .filter(|ms| (1..=MAX_SEGMENT_MS).contains(ms))
        .ok_or_else(|| StoreError::Contract("duration out of range".into()))?;
    let container: Container = get(HEADER_CONTAINER)?
        .parse()
        .map_err(StoreError::Contract)?;
    let codec: Codec = get(HEADER_CODEC)?.parse().map_err(StoreError::Contract)?;
    check_format(track, container, codec).map_err(StoreError::Contract)?;

    Ok(NewSegment {
        interview_id: interview_id.to_owned(),
        track,
        seq,
        started_at_ms,
        duration_ms,
        container,
        codec,
    })
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    const INTERVIEW: &str = "0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6";

    fn headers(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
        move |name| map.get(name).cloned()
    }

    fn camera() -> Vec<(&'static str, &'static str)> {
        vec![
            (HEADER_TRACK, "camera"),
            (HEADER_SEQ, "4"),
            (HEADER_STARTED_AT_MS, "1760245400123"),
            (HEADER_DURATION_MS, "10000"),
            (HEADER_CONTAINER, "mp4"),
            (HEADER_CODEC, "h264"),
        ]
    }

    #[test]
    fn reads_a_camera_segment() {
        let segment = segment_from_headers(INTERVIEW, headers(&camera())).expect("valid");
        assert_eq!(
            segment,
            NewSegment {
                interview_id: INTERVIEW.into(),
                track: Track::Camera,
                seq: 4,
                started_at_ms: 1_760_245_400_123,
                duration_ms: 10_000,
                container: Container::Mp4,
                codec: Codec::H264,
            }
        );
    }

    fn with(name: &'static str, value: &'static str) -> Vec<(&'static str, &'static str)> {
        let mut pairs = camera();
        pairs.retain(|(k, _)| *k != name);
        pairs.push((name, value));
        pairs
    }

    #[test]
    fn the_webview_cannot_write_screen_tracks() {
        let result = segment_from_headers(INTERVIEW, headers(&with(HEADER_TRACK, "screen-1")));
        assert!(matches!(result, Err(StoreError::Contract(_))));
    }

    #[test]
    fn rejects_bad_values() {
        for (name, value) in [
            (HEADER_SEQ, "-1"),
            (HEADER_SEQ, "four"),
            (HEADER_DURATION_MS, "0"),
            (HEADER_DURATION_MS, "60001"),
            (HEADER_CONTAINER, "mkv"),
            (HEADER_CODEC, "opus"),
            (HEADER_TRACK, "audio"),
        ] {
            let result = segment_from_headers(INTERVIEW, headers(&with(name, value)));
            assert!(
                matches!(result, Err(StoreError::Contract(_))),
                "{name}={value}"
            );
        }
    }

    #[test]
    fn rejects_missing_headers() {
        let mut pairs = camera();
        pairs.retain(|(k, _)| *k != HEADER_STARTED_AT_MS);
        assert!(segment_from_headers(INTERVIEW, headers(&pairs)).is_err());
    }
}
