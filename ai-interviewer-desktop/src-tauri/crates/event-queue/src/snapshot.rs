//! The server's snapshot requests (`proctoring.md`, "Changes" 2026-10-11): when it raises a
//! CRITICAL event it asks for a screen (and, where the camera matters, a camera) picture in the
//! heartbeat answer, and keeps asking in every answer until it hands out the upload slot or two
//! minutes pass. The tracker hands each request on once and drops expired ones.

use std::collections::HashMap;

use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;

use crate::event::parse_rfc3339_ms;

/// A request expires two minutes after the server made it.
pub const SNAPSHOT_TTL_MS: i64 = 120_000;
/// Request ids are UUIDs; anything longer or with other characters is refused.
const MAX_ID_LEN: usize = 64;

/// What the server wants a picture of.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SnapshotKind {
    Screen,
    Camera,
}

impl SnapshotKind {
    /// The name on the wire.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Screen => "screen",
            Self::Camera => "camera",
        }
    }
}

/// One entry of the heartbeat answer's `snapshot_requests`.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct SnapshotRequest {
    pub request_id: String,
    pub event_id: String,
    pub kind: SnapshotKind,
    /// Server time, RFC 3339 with a time zone.
    pub requested_at: String,
}

impl SnapshotRequest {
    /// When the server stops taking an answer, in server milliseconds; `None` when
    /// `requested_at` isn't a valid time with a zone.
    pub fn expires_at_ms(&self) -> Option<i64> {
        parse_rfc3339_ms(&self.requested_at).map(|at| at + SNAPSHOT_TTL_MS)
    }

    fn has_valid_id(&self) -> bool {
        !self.request_id.is_empty()
            && self.request_id.len() <= MAX_ID_LEN
            && self
                .request_id
                .chars()
                .all(|c| c.is_ascii_hexdigit() || c == '-')
    }
}

/// The requests already handed on, until they expire.
#[derive(Debug, Default)]
pub struct SnapshotTracker {
    seen: HashMap<String, i64>,
}

impl SnapshotTracker {
    /// Whether `request` is new, valid and not expired at `now_ms` (server time); if so it is
    /// remembered until it expires. Old entries are pruned on the way.
    pub fn accept(&mut self, request: &SnapshotRequest, now_ms: i64) -> bool {
        self.seen.retain(|_, expires_at| *expires_at > now_ms);
        let Some(expires_at) = request.expires_at_ms() else {
            return false;
        };
        if expires_at <= now_ms || !request.has_valid_id() {
            return false;
        }
        if self.seen.contains_key(&request.request_id) {
            return false;
        }
        self.seen.insert(request.request_id.clone(), expires_at);
        true
    }

    /// Forgets a request that couldn't be handed on, so the next answer may bring it again.
    pub fn forget(&mut self, request_id: &str) {
        self.seen.remove(request_id);
    }

    /// The requests remembered now.
    pub fn len(&self) -> usize {
        self.seen.len()
    }

    pub fn is_empty(&self) -> bool {
        self.seen.is_empty()
    }
}

/// Reads `snapshot_requests`, skipping entries this app can't read (an unknown `kind`), so
/// one odd entry never costs the rest of the heartbeat answer.
pub(crate) fn lenient_requests<'de, D>(deserializer: D) -> Result<Vec<SnapshotRequest>, D::Error>
where
    D: Deserializer<'de>,
{
    let values = Option::<Vec<Value>>::deserialize(deserializer)?.unwrap_or_default();
    Ok(values
        .into_iter()
        .filter_map(|value| serde_json::from_value(value).ok())
        .collect())
}
