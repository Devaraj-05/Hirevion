//! The Hirevion API client for the desktop app: DPoP-bound requests, server time and candidate sign-in.
//!
//! - [`ApiClient`] sends every request from Rust (the webview never sees a token), signs a DPoP
//!   proof for each one with the device key, retries a `use-dpop-nonce` challenge once and turns
//!   RFC 9457 problems into [`ApiError::Problem`].
//! - [`auth`] maps `docs/api/contracts/candidate-auth.md` field for field.

pub mod auth;
mod client;
mod clock;
mod error;

pub use client::{ApiClient, user_agent};
pub use clock::ClockSample;
pub use error::ApiError;
pub use reqwest::Method;
pub use url::Url;
