use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use p256::ecdsa::signature::Verifier as _;
use p256::ecdsa::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::SecurityError;

/// A P-256 public key as a JWK (`{"kty":"EC","crv":"P-256","x","y"}`, coordinates base64url).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Jwk {
    pub kty: String,
    pub crv: String,
    pub x: String,
    pub y: String,
}

impl Jwk {
    /// Builds the JWK from the 32-byte big-endian affine coordinates.
    pub fn from_coordinates(x: &[u8], y: &[u8]) -> Self {
        Self {
            kty: "EC".into(),
            crv: "P-256".into(),
            x: b64(x),
            y: b64(y),
        }
    }

    /// The RFC 7638 SHA-256 thumbprint, base64url: the device id (`jkt`).
    pub fn thumbprint(&self) -> String {
        jwk_thumbprint(&[
            ("crv", &self.crv),
            ("kty", &self.kty),
            ("x", &self.x),
            ("y", &self.y),
        ])
    }

    /// Verifies an ES256 signature (64-byte `r||s` over SHA-256 of `message`) under this key.
    pub fn verify(&self, message: &[u8], signature: &[u8]) -> Result<(), SecurityError> {
        let key = self.verifying_key()?;
        let signature =
            Signature::from_slice(signature).map_err(|_| SecurityError::BadSignature)?;
        key.verify(message, &signature)
            .map_err(|_| SecurityError::BadSignature)
    }

    fn verifying_key(&self) -> Result<VerifyingKey, SecurityError> {
        if self.kty != "EC" || self.crv != "P-256" {
            return Err(SecurityError::InvalidKey(format!(
                "expected an EC P-256 key, got {} {}",
                self.kty, self.crv
            )));
        }
        let x = b64_decode(&self.x)?;
        let y = b64_decode(&self.y)?;
        if x.len() != 32 || y.len() != 32 {
            return Err(SecurityError::InvalidKey(
                "P-256 coordinates must be 32 bytes".into(),
            ));
        }
        let point = p256::EncodedPoint::from_affine_coordinates(
            p256::FieldBytes::from_slice(&x),
            p256::FieldBytes::from_slice(&y),
            false,
        );
        VerifyingKey::from_encoded_point(&point)
            .map_err(|_| SecurityError::InvalidKey("the point is not on P-256".into()))
    }
}

/// The RFC 7638 thumbprint of a JWK given as its required members.
///
/// The members are sorted by name and serialised as JSON without whitespace, then hashed with
/// SHA-256 and base64url-encoded. Pass only the required members for the key type
/// (`crv`, `kty`, `x`, `y` for EC; `e`, `kty`, `n` for RSA).
pub fn jwk_thumbprint(members: &[(&str, &str)]) -> String {
    let mut sorted = members.to_vec();
    sorted.sort_by(|a, b| a.0.cmp(b.0));
    let mut json = String::from("{");
    for (index, (name, value)) in sorted.iter().enumerate() {
        if index > 0 {
            json.push(',');
        }
        json.push_str(&json_string(name));
        json.push(':');
        json.push_str(&json_string(value));
    }
    json.push('}');
    b64(&Sha256::digest(json.as_bytes()))
}

fn json_string(value: &str) -> String {
    // Serialising a &str can't fail.
    serde_json::to_string(value).unwrap_or_default()
}

pub(crate) fn b64(data: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(data)
}

pub(crate) fn b64_decode(data: &str) -> Result<Vec<u8>, SecurityError> {
    URL_SAFE_NO_PAD
        .decode(data)
        .map_err(|e| SecurityError::InvalidKey(format!("bad base64url: {e}")))
}
