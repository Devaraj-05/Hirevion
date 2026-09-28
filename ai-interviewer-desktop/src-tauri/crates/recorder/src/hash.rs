//! SHA-256 through Windows CNG (FIPS 140 validated, hardware accelerated).

use std::fmt::Write as _;
use windows::Win32::Security::Cryptography::{BCRYPT_SHA256_ALG_HANDLE, BCryptHash};
use windows_core::Result;

/// The SHA-256 digest of `data`.
pub fn sha256(data: &[u8]) -> Result<[u8; 32]> {
    let mut digest = [0u8; 32];
    // SAFETY: the SHA-256 pseudo-handle needs no setup; both slices are valid for the call.
    unsafe { BCryptHash(BCRYPT_SHA256_ALG_HANDLE, None, data, &mut digest) }.ok()?;
    Ok(digest)
}

/// Lower-case hexadecimal.
#[must_use]
pub fn hex(bytes: &[u8]) -> String {
    bytes
        .iter()
        .fold(String::with_capacity(bytes.len() * 2), |mut text, byte| {
            let _ = write!(text, "{byte:02x}");
            text
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_the_fips_180_known_answers() {
        assert_eq!(
            hex(&sha256(b"abc").expect("hash")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            hex(&sha256(b"").expect("hash")),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn hex_is_lowercase_and_zero_padded() {
        assert_eq!(hex(&[0x00, 0x0f, 0xab]), "000fab");
    }
}
