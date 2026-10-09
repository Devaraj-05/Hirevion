//! Device keys (TPM or software), DPoP proofs, the DPAPI vault and integrity checks for the Hirevion desktop app.
//!
//! - [`Signer`] is a P-256 device key: [`NcryptKey`] on Windows (TPM-backed when possible),
//!   [`SoftwareKey`] for tests and as a last-resort fallback.
//! - [`dpop`] builds RFC 9449 proofs as `docs/api/contracts/README.md` describes them.
//! - [`Vault`] keeps small secrets (the refresh token) encrypted with DPAPI for the current user.
//! - [`integrity`] removes WebView2 environment overrides and detects debuggers.

pub mod dpop;
mod error;
pub mod integrity;
mod jwk;
#[cfg(windows)]
mod ncrypt;
mod signer;
mod vault;

pub use error::SecurityError;
pub use jwk::{Jwk, jwk_thumbprint};
#[cfg(windows)]
pub use ncrypt::NcryptKey;
pub use signer::{Signer, SoftwareKey};
pub use vault::Vault;

/// The name of the persisted device key (one per Windows user).
pub const DEVICE_KEY_NAME: &str = "Hirevion Device Key v1";
