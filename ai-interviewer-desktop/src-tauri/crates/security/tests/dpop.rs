//! DPoP proofs (RFC 9449) as the contracts README describes them.

use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use hv_security::{Signer, SoftwareKey, dpop};
use p256::ecdsa::signature::Verifier as _;
use p256::ecdsa::{Signature, VerifyingKey};
use sha2::{Digest, Sha256};

fn decode_part(part: &str) -> serde_json::Value {
    let bytes = URL_SAFE_NO_PAD.decode(part).expect("base64url");
    serde_json::from_slice(&bytes).expect("json")
}

/// Verifies a compact JWS independently of the crate, with p256 and the JWK in its header.
fn verify_independently(proof: &str) -> (serde_json::Value, serde_json::Value) {
    let parts: Vec<&str> = proof.split('.').collect();
    assert_eq!(parts.len(), 3, "compact JWS has three parts");
    let header = decode_part(parts[0]);
    let claims = decode_part(parts[1]);

    let x = URL_SAFE_NO_PAD
        .decode(header["jwk"]["x"].as_str().expect("x"))
        .expect("x bytes");
    let y = URL_SAFE_NO_PAD
        .decode(header["jwk"]["y"].as_str().expect("y"))
        .expect("y bytes");
    let point = p256::EncodedPoint::from_affine_coordinates(
        p256::FieldBytes::from_slice(&x),
        p256::FieldBytes::from_slice(&y),
        false,
    );
    let key = VerifyingKey::from_encoded_point(&point).expect("valid point");
    let signature = Signature::from_slice(&URL_SAFE_NO_PAD.decode(parts[2]).expect("sig"))
        .expect("64-byte r||s");
    let signing_input = format!("{}.{}", parts[0], parts[1]);
    key.verify(signing_input.as_bytes(), &signature)
        .expect("signature verifies under the header's JWK");
    (header, claims)
}

#[test]
fn proof_verifies_and_carries_the_contract_claims() {
    let key = SoftwareKey::generate();
    let proof = dpop::proof(
        &key,
        "POST",
        "https://api.hirevion.localhost/api/v1/candidate-auth/me?x=1#frag",
        Some("access-token-123"),
        Some("server-nonce"),
        1_760_000_000,
    )
    .expect("proof");

    let (header, claims) = verify_independently(&proof);
    assert_eq!(header["typ"], "dpop+jwt");
    assert_eq!(header["alg"], "ES256");
    assert_eq!(header["jwk"]["kty"], "EC");
    assert_eq!(header["jwk"]["crv"], "P-256");
    assert!(header["jwk"].get("d").is_none(), "no private part");

    assert_eq!(claims["htm"], "POST");
    assert_eq!(
        claims["htu"],
        "https://api.hirevion.localhost/api/v1/candidate-auth/me"
    );
    assert_eq!(claims["iat"], 1_760_000_000);
    assert_eq!(claims["nonce"], "server-nonce");
    let expected_ath = URL_SAFE_NO_PAD.encode(Sha256::digest(b"access-token-123"));
    assert_eq!(claims["ath"], expected_ath.as_str());
    assert_eq!(dpop::access_token_hash("access-token-123"), expected_ath);

    let jti = claims["jti"].as_str().expect("jti");
    let parsed = uuid_like(jti);
    assert!(parsed, "jti is a UUID: {jti}");
}

#[test]
fn proof_without_token_or_nonce_omits_ath_and_nonce() {
    let key = SoftwareKey::generate();
    let proof = dpop::proof(
        &key,
        "GET",
        "https://api.example.test/api/v1/time",
        None,
        None,
        42,
    )
    .expect("proof");
    let (_, claims) = verify_independently(&proof);
    assert!(claims.get("ath").is_none());
    assert!(claims.get("nonce").is_none());
    assert_eq!(claims["htu"], "https://api.example.test/api/v1/time");
}

#[test]
fn every_proof_has_a_fresh_jti() {
    let key = SoftwareKey::generate();
    let a = dpop::proof(&key, "GET", "https://a.test/x", None, None, 1).expect("a");
    let b = dpop::proof(&key, "GET", "https://a.test/x", None, None, 1).expect("b");
    let (_, ca) = verify_independently(&a);
    let (_, cb) = verify_independently(&b);
    assert_ne!(ca["jti"], cb["jti"]);
}

#[test]
fn crate_verify_accepts_its_own_proofs_and_rejects_tampering() {
    let key = SoftwareKey::generate();
    let proof = dpop::proof(&key, "GET", "https://a.test/x?q", Some("t"), None, 7).expect("proof");
    let verified = dpop::verify(&proof).expect("verifies");
    assert_eq!(verified.header.jwk, key.public_jwk());
    assert_eq!(verified.claims.htu, "https://a.test/x");
    assert_eq!(
        verified.claims.ath.as_deref(),
        Some(dpop::access_token_hash("t").as_str())
    );
    assert_eq!(verified.claims.iat, 7);

    let parts: Vec<&str> = proof.split('.').collect();
    let other_claims =
        URL_SAFE_NO_PAD.encode(br#"{"jti":"x","htm":"GET","htu":"https://evil.test/","iat":7}"#);
    let tampered = format!("{}.{}.{}", parts[0], other_claims, parts[2]);
    assert!(dpop::verify(&tampered).is_err());
}

fn uuid_like(s: &str) -> bool {
    let groups: Vec<&str> = s.split('-').collect();
    groups.len() == 5
        && groups.iter().map(|g| g.len()).eq([8, 4, 4, 4, 12])
        && s.chars().all(|c| c == '-' || c.is_ascii_hexdigit())
}
