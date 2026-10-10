//! The candidate app (SP-08a): its state and the commands the webview calls instead of the API.
//! SP-08b adds the interview services: monitoring, proctoring events and recordings.

pub mod commands;
mod error;
pub mod interview;
mod proctoring;
mod progress;
pub mod service_commands;
mod services;
pub mod state;
mod stub;
mod views;

pub use state::AppState;
