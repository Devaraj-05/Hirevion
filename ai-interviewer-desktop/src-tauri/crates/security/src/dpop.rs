//! DPoP proofs (RFC 9449), as `docs/api/contracts/README.md` specifies them.
//!
//! A proof is a compact JWS: header `{"typ":"dpop+jwt","alg":"ES256","jwk":…}` and claims
//! `jti` (a fresh UUID), `htm`, `htu` (no query or fragment), `iat` (server time),
//! `ath` (when an access token is sent) and `nonce` (when the server asked for one).

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::jwk::{b64, b64_decode};
use crate::{Jwk, SecurityError, Signer};

/// The proof's JOSE header.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofHeader {
    pub typ: String,
    pub alg: String,
    pub jwk: Jwk,
}

/// The proof's claims.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProofClaims {
    pub jti: String,
    pub htm: String,
    pub htu: String,
    pub iat: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ath: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub nonce: Option<String>,
}

/// A proof whose signature verified under the JWK in its own header.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedProof {
    pub header: ProofHeader,
    pub claims: ProofClaims,
}

const TYP: &str = "dpop+jwt";
const ALG: &str = "ES256";

/// Builds and signs a DPoP proof for one request.
///
/// - `method` is the HTTP method (`htm`), as sent.
/// - `url` is the request URL; the query and fragment are dropped for `htu`.
/// - `access_token`, when the request carries one, adds `ath`.
/// - `nonce`, when the server gave one, adds `nonce`.
/// - `iat_unix` is the server time in seconds.
pub fn proof(
    signer: &dyn Signer,
    method: &str,
    url: &str,
    access_token: Option<&str>,
    nonce: Option<&str>,
    iat_unix: i64,
) -> Result<String, SecurityError> {
    let header = ProofHeader {
        typ: TYP.into(),
        alg: ALG.into(),
        jwk: signer.public_jwk(),
    };
    let claims = ProofClaims {
        jti: uuid::Uuid::new_v4().to_string(),
        htm: method.into(),
        htu: htu(url).into(),
        iat: iat_unix,
        ath: access_token.map(access_token_hash),
        nonce: nonce.map(str::to_owned),
    };
    let signing_input = format!("{}.{}", encode_json(&header)?, encode_json(&claims)?);
    let signature = signer.sign(signing_input.as_bytes())?;
    Ok(format!("{signing_input}.{}", b64(&signature)))
}

/// The `ath` claim: base64url SHA-256 of the access token.
pub fn access_token_hash(access_token: &str) -> String {
    b64(&Sha256::digest(access_token.as_bytes()))
}

/// The `htu` claim: the URL without its query or fragment.
pub fn htu(url: &str) -> &str {
    match url.find(['?', '#']) {
        Some(end) => &url[..end],
        None => url,
    }
}

/// Parses a proof and checks its header and its signature under the header's JWK.
///
/// This doesn't check `iat`, `jti` replay, `htm`/`htu` or `ath` against a request: the
/// server does that. It's for tests and diagnostics.
pub fn verify(proof: &str) -> Result<VerifiedProof, SecurityError> {
    let mut parts = proof.split('.');
    let (Some(header_b64), Some(claims_b64), Some(signature_b64), None) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return Err(SecurityError::InvalidProof(
            "expected three dot-separated parts".into(),
        ));
    };
    let header: ProofHeader = decode_json(header_b64)?;
    if header.typ != TYP || header.alg != ALG {
        return Err(SecurityError::InvalidProof(format!(
            "unexpected header typ={} alg={}",
            header.typ, header.alg
        )));
    }
    let claims: ProofClaims = decode_json(claims_b64)?;
    let signature = b64_decode(signature_b64)?;
    header
        .jwk
        .verify(format!("{header_b64}.{claims_b64}").as_bytes(), &signature)?;
    Ok(VerifiedProof { header, claims })
}

fn encode_json<T: Serialize>(value: &T) -> Result<String, SecurityError> {
    serde_json::to_vec(value)
        .map(|json| b64(&json))
        .map_err(|e| SecurityError::Encoding(e.to_string()))
}

fn decode_json<T: for<'de> Deserialize<'de>>(part: &str) -> Result<T, SecurityError> {
    let bytes = b64_decode(part).map_err(|e| SecurityError::InvalidProof(e.to_string()))?;
    serde_json::from_slice(&bytes).map_err(|e| SecurityError::InvalidProof(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::htu;

    #[test]
    fn htu_drops_query_and_fragment() {
        assert_eq!(htu("https://a.test/p?q=1"), "https://a.test/p");
        assert_eq!(htu("https://a.test/p#f"), "https://a.test/p");
        assert_eq!(htu("https://a.test/p#f?x"), "https://a.test/p");
        assert_eq!(htu("https://a.test/p"), "https://a.test/p");
    }
}
