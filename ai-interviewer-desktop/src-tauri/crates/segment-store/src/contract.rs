//! The track, container and codec rules of `docs/api/contracts/recordings.md`.

use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// The largest segment the server accepts (`413 segment-too-large` above it).
pub const MAX_SEGMENT_BYTES: usize = 50_000_000;
/// The longest segment the server accepts.
pub const MAX_SEGMENT_MS: u32 = 60_000;
/// The highest display number: `screen-1` … `screen-99`.
pub const MAX_SCREENS: u16 = 99;

/// A recorded track: `screen-<n>` (one per display, from 1), `camera` or `mic`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Track {
    Screen(u16),
    Camera,
    Mic,
}

impl Track {
    /// Whether the desktop's native recorder (not the webview) produces this track.
    #[must_use]
    pub fn is_screen(self) -> bool {
        matches!(self, Self::Screen(_))
    }
}

impl fmt::Display for Track {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Screen(n) => write!(f, "screen-{n}"),
            Self::Camera => f.write_str("camera"),
            Self::Mic => f.write_str("mic"),
        }
    }
}

impl FromStr for Track {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "camera" => Ok(Self::Camera),
            "mic" => Ok(Self::Mic),
            _ => value
                .strip_prefix("screen-")
                // Digits only: no sign, no leading zero, so the name round-trips.
                .filter(|n| n.bytes().all(|b| b.is_ascii_digit()) && !n.starts_with('0'))
                .and_then(|n| n.parse::<u16>().ok())
                .filter(|n| (1..=MAX_SCREENS).contains(n))
                .map(Self::Screen)
                .ok_or_else(|| format!("unknown track {value:?}")),
        }
    }
}

impl Serialize for Track {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for Track {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        text.parse().map_err(serde::de::Error::custom)
    }
}

/// The file format of a segment.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Container {
    Mp4,
    Webm,
}

impl Container {
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Mp4 => "mp4",
            Self::Webm => "webm",
        }
    }
}

impl FromStr for Container {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "mp4" => Ok(Self::Mp4),
            "webm" => Ok(Self::Webm),
            _ => Err(format!("unknown container {value:?}")),
        }
    }
}

/// The codec of a segment's only stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Codec {
    H264,
    Vp8,
    Opus,
    Aac,
}

impl Codec {
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::H264 => "h264",
            Self::Vp8 => "vp8",
            Self::Opus => "opus",
            Self::Aac => "aac",
        }
    }
}

impl FromStr for Codec {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "h264" => Ok(Self::H264),
            "vp8" => Ok(Self::Vp8),
            "opus" => Ok(Self::Opus),
            "aac" => Ok(Self::Aac),
            _ => Err(format!("unknown codec {value:?}")),
        }
    }
}

/// Checks the container and codec the contract allows for `track`: screens are MP4/H.264,
/// the camera MP4/H.264 or WebM/VP8, the microphone WebM/Opus or MP4/AAC.
pub fn check_format(track: Track, container: Container, codec: Codec) -> Result<(), String> {
    let allowed = match track {
        Track::Screen(_) => matches!((container, codec), (Container::Mp4, Codec::H264)),
        Track::Camera => matches!(
            (container, codec),
            (Container::Mp4, Codec::H264) | (Container::Webm, Codec::Vp8)
        ),
        Track::Mic => matches!(
            (container, codec),
            (Container::Webm, Codec::Opus) | (Container::Mp4, Codec::Aac)
        ),
    };
    if allowed {
        Ok(())
    } else {
        Err(format!(
            "{track} can't be {}/{}",
            container.as_str(),
            codec.as_str()
        ))
    }
}

/// The MIME type of a segment, for logs and fallbacks (the server sends the upload headers).
#[must_use]
pub fn content_type(track: Track, container: Container) -> &'static str {
    match (track, container) {
        (Track::Mic, Container::Mp4) => "audio/mp4",
        (Track::Mic, Container::Webm) => "audio/webm",
        (_, Container::Mp4) => "video/mp4",
        (_, Container::Webm) => "video/webm",
    }
}

/// The canonical (lower-case, hyphenated) form of an interview id, or `None` when it isn't a
/// UUID. Interview ids name directories and vault entries, so nothing else is accepted.
#[must_use]
pub fn canonical_interview_id(value: &str) -> Option<String> {
    uuid::Uuid::parse_str(value)
        .ok()
        .filter(|_| value.len() == 36)
        .map(|id| id.hyphenated().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn track_names_round_trip() {
        for name in ["screen-1", "screen-2", "screen-99", "camera", "mic"] {
            let track: Track = name.parse().expect(name);
            assert_eq!(track.to_string(), name);
        }
    }

    #[test]
    fn rejects_unknown_tracks() {
        for name in [
            "screen-0",
            "screen-100",
            "screen-01",
            "screen-+1",
            "screen-",
            "audio",
            "",
        ] {
            assert!(name.parse::<Track>().is_err(), "{name}");
        }
    }

    #[test]
    fn checks_formats_per_track() {
        assert!(check_format(Track::Screen(1), Container::Mp4, Codec::H264).is_ok());
        assert!(check_format(Track::Screen(1), Container::Webm, Codec::Vp8).is_err());
        assert!(check_format(Track::Camera, Container::Webm, Codec::Vp8).is_ok());
        assert!(check_format(Track::Camera, Container::Mp4, Codec::H264).is_ok());
        assert!(check_format(Track::Camera, Container::Webm, Codec::Opus).is_err());
        assert!(check_format(Track::Mic, Container::Webm, Codec::Opus).is_ok());
        assert!(check_format(Track::Mic, Container::Mp4, Codec::Aac).is_ok());
        assert!(check_format(Track::Mic, Container::Mp4, Codec::Opus).is_err());
    }

    #[test]
    fn content_types_follow_the_track_kind() {
        assert_eq!(content_type(Track::Screen(2), Container::Mp4), "video/mp4");
        assert_eq!(content_type(Track::Camera, Container::Webm), "video/webm");
        assert_eq!(content_type(Track::Mic, Container::Webm), "audio/webm");
    }

    #[test]
    fn interview_ids_must_be_uuids() {
        assert_eq!(
            canonical_interview_id("0192F3A4-5B6C-7D8E-9FA0-B1C2D3E4F5A6").as_deref(),
            Some("0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6")
        );
        assert_eq!(canonical_interview_id("../../etc"), None);
        assert_eq!(
            canonical_interview_id("0192f3a45b6c7d8e9fa0b1c2d3e4f5a6"),
            None
        );
    }
}
