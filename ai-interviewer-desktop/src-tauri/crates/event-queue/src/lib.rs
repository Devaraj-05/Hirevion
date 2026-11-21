//! Proctoring events for the Hirevion desktop app (`docs/api/contracts/proctoring.md`).
//!
//! - [`DeviceRules`] turns `hv-monitor` observations into [`EventDraft`]s: the §61
//!   [`PolicyMatcher`] for processes, and the on-device temporal rules of the §6.12 table
//!   (focus and minimise only after 3 s, with the duration).
//! - [`EventQueue`] numbers drafts (`seq`, never reused), keeps them on disk until the server
//!   acknowledges them, and survives restarts.
//! - [`Uploader`] sends the queue in batches, resends what the server says is missing, backs
//!   off on failure, sends heartbeats, and stops for good on `409 proctor-session-closed`.
//!   The server's snapshot requests in heartbeat answers come out once each
//!   ([`UploaderHandle::snapshot_requests`], [`SnapshotTracker`]).
//!
//! No event ever carries what a key typed: nothing here reads input (a test enforces that).

mod close;
mod event;
mod policy;
mod queue;
mod rules;
mod snapshot;
mod uploader;

pub use close::{AppToClose, AppsToClose, apps_to_close};
pub use event::{
    EventDraft, EventName, Evidence, ProctorEvent, Source, parse_rfc3339_ms, rfc3339_ms,
};
pub use policy::{
    AppRule, AppRules, BlockMatch, Condition, MatchKind, PolicyMatcher, SessionPolicy,
    SeverityHint, Threshold,
};
pub use queue::EventQueue;
pub use rules::{DeviceRules, INVENTORY_BUDGET_BYTES, Thresholds};
pub use snapshot::{SNAPSHOT_TTL_MS, SnapshotKind, SnapshotRequest, SnapshotTracker};
pub use uploader::{
    ApiSource, DeviceStatus, SESSION_CLOSED, UploadState, Uploader, UploaderConfig, UploaderHandle,
    open_session,
};
