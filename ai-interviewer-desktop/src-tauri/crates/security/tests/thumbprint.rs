//! RFC 7638 JWK thumbprints, checked against the RFCs' own examples.

use hv_security::{Jwk, Signer, SoftwareKey, jwk_thumbprint};

/// RFC 7638 §3.1: the RSA example key and its thumbprint.
#[test]
fn rfc7638_example_thumbprint() {
    let n = concat!(
        "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAt",
        "VT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn6",
        "4tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FD",
        "W2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n9",
        "1CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINH",
        "aQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw",
    );
    // Member order must not matter: the function sorts them.
    let thumbprint = jwk_thumbprint(&[("n", n), ("kty", "RSA"), ("e", "AQAB")]);
    assert_eq!(thumbprint, "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs");
}

/// RFC 9449 §6.1: the EC key from the DPoP examples and its `jkt`.
#[test]
fn rfc9449_ec_key_thumbprint() {
    let jwk = Jwk {
        kty: "EC".into(),
        crv: "P-256".into(),
        x: "l8tFrhx-34tV3hRICRDY9zCkDlpBhF42UQUfWVAWBFs".into(),
        y: "9VE4jf_Ok_o64zbTTlcuNJajHmt6v9TDVrU0CdvGRDA".into(),
    };
    assert_eq!(
        jwk.thumbprint(),
        "0ZcOCORZNYy-DWpqq30jZyJGHTN0d2HglBV3uiguA4I"
    );
}

#[test]
fn software_key_thumbprint_is_its_jwk_thumbprint() {
    let key = SoftwareKey::generate();
    let jwk = key.public_jwk();
    assert_eq!(jwk.kty, "EC");
    assert_eq!(jwk.crv, "P-256");
    // 32-byte coordinates, base64url without padding.
    assert_eq!(jwk.x.len(), 43);
    assert_eq!(jwk.y.len(), 43);
    assert_eq!(key.thumbprint(), jwk.thumbprint());
    assert!(!key.hardware_backed());
}

#[test]
fn software_key_signature_verifies_under_its_jwk() {
    let key = SoftwareKey::generate();
    let signature = key.sign(b"hello").expect("sign");
    key.public_jwk()
        .verify(b"hello", &signature)
        .expect("signature verifies");
    assert!(key.public_jwk().verify(b"other", &signature).is_err());
}

#[test]
fn software_key_round_trips_through_its_secret_bytes() {
    let key = SoftwareKey::generate();
    let again = SoftwareKey::from_secret_bytes(&key.secret_bytes()).expect("restore");
    assert_eq!(key.public_jwk(), again.public_jwk());
    assert!(SoftwareKey::from_secret_bytes(&[0u8; 32]).is_err());
}
