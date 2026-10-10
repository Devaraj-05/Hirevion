//! The candidate app (SP-08a): its state and the commands the webview calls instead of the API.

pub mod commands;
mod error;
pub mod interview;
pub mod state;
mod stub;
mod views;

pub use state::AppState;
