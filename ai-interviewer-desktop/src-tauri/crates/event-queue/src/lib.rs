//! Proctoring events for the Hirevion desktop app (`docs/api/contracts/proctoring.md`).
//!
//! - [`DeviceRules`] turns `hv-monitor` observations into [`EventDraft`]s: the §61
//!   [`PolicyMatcher`] for processes, and the on-device temporal rules of the §6.12 table
//!   (focus and minimise only after 3 s, with the duration).
//! - [`EventQueue`] numbers drafts (`seq`, never reused), keeps them on disk until the server
//!   acknowledges them, and survives restarts.
//! - [`Uploader`] sends the queue in batches, resends what the server says is missing, backs
//!   off on failure, sends heartbeats, and stops for good on `409 proctor-session-closed`.
//!
//! No event ever carries what a key typed: nothing here reads input (a test enforces that).

mod event;
mod policy;
mod queue;
mod rules;
mod uploader;

pub use event::{EventDraft, EventName, Evidence, ProctorEvent, Source, rfc3339_ms};
pub use policy::{
    AppRule, AppRules, BlockMatch, Condition, MatchKind, PolicyMatcher, SessionPolicy,
    SeverityHint, Threshold,
};
pub use queue::EventQueue;
pub use rules::{DeviceRules, Thresholds};
pub use uploader::{
    ApiSource, DeviceStatus, SESSION_CLOSED, UploadState, Uploader, UploaderConfig, UploaderHandle,
    open_session,
};
