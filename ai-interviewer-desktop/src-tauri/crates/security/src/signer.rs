use p256::ecdsa::signature::Signer as _;
use p256::ecdsa::{Signature, SigningKey};
use rand_core::OsRng;

use crate::{Jwk, SecurityError};

/// A P-256 device key that signs with ES256.
pub trait Signer: Send + Sync {
    /// The public key, `{"kty":"EC","crv":"P-256","x","y"}` with base64url coordinates.
    fn public_jwk(&self) -> Jwk;

    /// The RFC 7638 SHA-256 thumbprint of [`Signer::public_jwk`], base64url: the device id (`jkt`).
    fn thumbprint(&self) -> String {
        self.public_jwk().thumbprint()
    }

    /// An ES256 signature: 64 bytes `r||s` over SHA-256(`message`).
    fn sign(&self, message: &[u8]) -> Result<[u8; 64], SecurityError>;

    /// Whether the private key lives in hardware (the TPM).
    fn hardware_backed(&self) -> bool;
}

/// A P-256 key held in process memory: for tests, and the fallback when no key store works.
pub struct SoftwareKey {
    key: SigningKey,
    jwk: Jwk,
}

impl SoftwareKey {
    /// A new random key from the operating system's RNG.
    pub fn generate() -> Self {
        Self::from_signing_key(SigningKey::random(&mut OsRng))
    }

    /// Restores a key from its 32-byte big-endian private scalar.
    pub fn from_secret_bytes(bytes: &[u8]) -> Result<Self, SecurityError> {
        let key = SigningKey::from_slice(bytes)
            .map_err(|_| SecurityError::InvalidKey("not a valid P-256 private scalar".into()))?;
        Ok(Self::from_signing_key(key))
    }

    /// The 32-byte private scalar, to persist the fallback key (in the [`crate::Vault`] only).
    pub fn secret_bytes(&self) -> Vec<u8> {
        self.key.to_bytes().to_vec()
    }

    fn from_signing_key(key: SigningKey) -> Self {
        let point = key.verifying_key().to_encoded_point(false);
        // An uncompressed point always has both coordinates.
        let x = point.x().map(|x| x.to_vec()).unwrap_or_default();
        let y = point.y().map(|y| y.to_vec()).unwrap_or_default();
        Self {
            jwk: Jwk::from_coordinates(&x, &y),
            key,
        }
    }
}

impl std::fmt::Debug for SoftwareKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SoftwareKey")
            .field("jwk", &self.jwk)
            .finish_non_exhaustive()
    }
}

impl Signer for SoftwareKey {
    fn public_jwk(&self) -> Jwk {
        self.jwk.clone()
    }

    fn sign(&self, message: &[u8]) -> Result<[u8; 64], SecurityError> {
        let signature: Signature = self.key.sign(message);
        let mut out = [0u8; 64];
        out.copy_from_slice(&signature.to_bytes());
        Ok(out)
    }

    fn hardware_backed(&self) -> bool {
        false
    }
}
