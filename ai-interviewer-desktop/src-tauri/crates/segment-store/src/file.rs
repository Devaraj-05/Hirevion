//! The encrypted segment file.
//!
//! ```text
//! "HVSEG\0v1" | u32 LE header length | header JSON | 96-bit nonce | AES-256-GCM ciphertext + tag
//! ```
//!
//! Everything before the nonce is the associated data, so the header (interview, track, seq,
//! timing, size and the plaintext's SHA-256) is authenticated with the video: a file can't be
//! renamed into another segment's place, and a file whose manifest row was lost in a crash can
//! be adopted again from its own header.

use aes_gcm::aead::{Aead, AeadCore, KeyInit, OsRng, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{Codec, Container, StoreError, Track};

const MAGIC: &[u8; 8] = b"HVSEG\0v1";
const NONCE_LEN: usize = 12;
/// Headers are a few hundred bytes; anything bigger isn't one of ours.
const MAX_HEADER: usize = 4_096;

/// What a segment file says about itself.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct FileHeader {
    pub interview_id: String,
    pub track: Track,
    pub seq: u64,
    pub started_at_ms: i64,
    pub duration_ms: u32,
    pub bytes: u64,
    pub sha256: String,
    pub container: Container,
    pub codec: Codec,
}

/// Encrypts `plain` under `key` with a fresh random nonce.
pub(crate) fn seal(
    key: &[u8; 32],
    header: &FileHeader,
    plain: &[u8],
) -> Result<Vec<u8>, StoreError> {
    let json = serde_json::to_vec(header).map_err(|e| StoreError::Corrupt(e.to_string()))?;
    let json_len = u32::try_from(json.len())
        .ok()
        .filter(|&len| len as usize <= MAX_HEADER)
        .ok_or_else(|| StoreError::Corrupt("segment header too large".into()))?;
    let mut out = Vec::with_capacity(12 + json.len() + NONCE_LEN + plain.len() + 16);
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&json_len.to_le_bytes());
    out.extend_from_slice(&json);
    let aad_len = out.len();

    let cipher = Aes256Gcm::new(key.into());
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
    let sealed = cipher
        .encrypt(
            &nonce,
            Payload {
                msg: plain,
                aad: &out[..aad_len],
            },
        )
        .map_err(|_| StoreError::Corrupt("encryption failed".into()))?;
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&sealed);
    Ok(out)
}

/// The header of a segment file, unauthenticated (enough to find its key).
pub(crate) fn peek_header(bytes: &[u8]) -> Result<(FileHeader, usize), StoreError> {
    let corrupt = |why: &str| StoreError::Corrupt(why.to_owned());
    if bytes.get(..MAGIC.len()) != Some(MAGIC.as_slice()) {
        return Err(corrupt("not a segment file"));
    }
    let len_bytes: [u8; 4] = bytes
        .get(8..12)
        .and_then(|b| b.try_into().ok())
        .ok_or_else(|| corrupt("truncated header"))?;
    let len = u32::from_le_bytes(len_bytes) as usize;
    if len > MAX_HEADER {
        return Err(corrupt("header too large"));
    }
    let json = bytes
        .get(12..12 + len)
        .ok_or_else(|| corrupt("truncated header"))?;
    let header: FileHeader =
        serde_json::from_slice(json).map_err(|e| StoreError::Corrupt(e.to_string()))?;
    Ok((header, 12 + len))
}

/// Decrypts a segment file, checking that the header is authentic and that the plaintext has
/// the size and SHA-256 the header declares.
pub(crate) fn open(key: &[u8; 32], bytes: &[u8]) -> Result<(FileHeader, Vec<u8>), StoreError> {
    let (header, aad_len) = peek_header(bytes)?;
    let nonce = bytes
        .get(aad_len..aad_len + NONCE_LEN)
        .ok_or_else(|| StoreError::Corrupt("truncated nonce".into()))?;
    let cipher = Aes256Gcm::new(key.into());
    let plain = cipher
        .decrypt(
            Nonce::from_slice(nonce),
            Payload {
                msg: &bytes[aad_len + NONCE_LEN..],
                aad: &bytes[..aad_len],
            },
        )
        .map_err(|_| StoreError::Corrupt("authentication failed".into()))?;
    if plain.len() as u64 != header.bytes || sha256_hex(&plain) != header.sha256 {
        return Err(StoreError::Corrupt(
            "the plaintext doesn't match its header".into(),
        ));
    }
    Ok((header, plain))
}

/// Lower-case hexadecimal SHA-256, as the contract sends it.
#[must_use]
pub fn sha256_hex(data: &[u8]) -> String {
    use std::fmt::Write as _;
    Sha256::digest(data)
        .iter()
        .fold(String::with_capacity(64), |mut text, byte| {
            let _ = write!(text, "{byte:02x}");
            text
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn header(plain: &[u8]) -> FileHeader {
        FileHeader {
            interview_id: "0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6".into(),
            track: Track::Mic,
            seq: 0,
            started_at_ms: 1,
            duration_ms: 10_000,
            bytes: plain.len() as u64,
            sha256: sha256_hex(plain),
            container: Container::Webm,
            codec: Codec::Opus,
        }
    }

    #[test]
    fn round_trips_and_uses_a_fresh_nonce_each_time() {
        let key = [7u8; 32];
        let plain = b"opus frames";
        let first = seal(&key, &header(plain), plain).expect("seal");
        let second = seal(&key, &header(plain), plain).expect("seal");
        assert_ne!(first, second, "nonces must never repeat");
        let (read, opened) = open(&key, &first).expect("open");
        assert_eq!(opened, plain);
        assert_eq!(read, header(plain));
    }

    #[test]
    fn the_wrong_key_fails_authentication() {
        let plain = b"opus frames";
        let sealed = seal(&[7u8; 32], &header(plain), plain).expect("seal");
        assert!(matches!(
            open(&[8u8; 32], &sealed),
            Err(StoreError::Corrupt(_))
        ));
    }

    #[test]
    fn garbage_is_not_a_segment() {
        assert!(peek_header(b"RIFF....").is_err());
        assert!(peek_header(b"HVSEG\0v1\xff\xff\xff\xff").is_err());
        assert!(open(&[0u8; 32], b"HVSEG\0v1").is_err());
    }
}
