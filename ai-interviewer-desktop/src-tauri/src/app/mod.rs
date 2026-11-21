//! The candidate app (SP-08a): its state and the commands the webview calls instead of the API.
//! SP-08b adds the interview services: monitoring, proctoring events and recordings.

pub mod commands;
pub mod error;
pub mod interview;
mod proctoring;
pub mod service_commands;
mod services;
mod snapshots;
pub mod state;
mod stub;
pub mod third_eye;
pub mod update;
mod views;

pub use state::AppState;
