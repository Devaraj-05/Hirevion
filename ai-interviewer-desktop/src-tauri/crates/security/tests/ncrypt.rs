//! The persisted NCrypt device key, using the software key storage provider
//! (CI runners have no usable TPM, and TPM keys are slow to create).
#![cfg(windows)]

use hv_security::{NcryptKey, Signer, dpop};

fn unique_name() -> String {
    format!("Hirevion Test Key {}", uuid::Uuid::new_v4())
}

#[test]
fn create_sign_verify_reopen_and_delete() {
    let name = unique_name();

    let key = NcryptKey::open_or_create(&name, false).expect("create");
    assert!(!key.hardware_backed(), "software provider is not hardware");
    assert_eq!(key.name(), name);

    let jwk = key.public_jwk();
    assert_eq!(jwk.kty, "EC");
    assert_eq!(jwk.crv, "P-256");
    assert_eq!(key.thumbprint(), jwk.thumbprint());

    let signature = key.sign(b"device message").expect("sign");
    jwk.verify(b"device message", &signature)
        .expect("NCrypt signature verifies under the exported JWK");
    assert!(jwk.verify(b"another message", &signature).is_err());

    // A DPoP proof from the device key verifies too.
    let proof = dpop::proof(&key, "GET", "https://a.test/x", Some("t"), None, 1).expect("proof");
    assert_eq!(dpop::verify(&proof).expect("verifies").header.jwk, jwk);

    // The key is persisted: opening it again gives the same public key.
    drop(key);
    let reopened = NcryptKey::open_or_create(&name, false).expect("reopen");
    assert_eq!(reopened.public_jwk(), jwk);

    reopened.delete().expect("delete");

    // After deletion the name creates a brand-new key.
    let fresh = NcryptKey::open_or_create(&name, false).expect("recreate");
    assert_ne!(fresh.public_jwk(), jwk);
    fresh.delete().expect("delete fresh");
}

/// Needs a TPM 2.0, so it only runs on request: `cargo test -p hv-security -- --ignored`.
/// Without a usable TPM it still passes, through the software fallback.
#[test]
#[ignore = "uses the TPM; run manually on a PC that has one"]
fn tpm_key_round_trip_or_software_fallback() {
    let name = unique_name();
    let key = NcryptKey::open_or_create(&name, true).expect("create");
    eprintln!("hardware_backed = {}", key.hardware_backed());
    let signature = key.sign(b"tpm").expect("sign");
    key.public_jwk()
        .verify(b"tpm", &signature)
        .expect("verifies");
    let jwk = key.public_jwk();
    drop(key);
    let reopened = NcryptKey::open_or_create(&name, true).expect("reopen");
    assert_eq!(reopened.public_jwk(), jwk, "the same key is found again");
    reopened.delete().expect("delete");
}

#[test]
fn concurrent_signing_is_safe() {
    let name = unique_name();
    let key = std::sync::Arc::new(NcryptKey::open_or_create(&name, false).expect("create"));
    let jwk = key.public_jwk();
    let threads: Vec<_> = (0..4)
        .map(|i| {
            let key = key.clone();
            std::thread::spawn(move || {
                let message = format!("message {i}");
                (message.clone(), key.sign(message.as_bytes()).expect("sign"))
            })
        })
        .collect();
    for thread in threads {
        let (message, signature) = thread.join().expect("thread");
        jwk.verify(message.as_bytes(), &signature)
            .expect("verifies");
    }
    std::sync::Arc::try_unwrap(key)
        .expect("sole owner")
        .delete()
        .expect("delete");
}
