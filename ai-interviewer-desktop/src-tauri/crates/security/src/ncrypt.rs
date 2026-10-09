//! The persisted device key in a Windows key storage provider (CNG / NCrypt).

use std::sync::{Mutex, PoisonError};

use sha2::{Digest, Sha256};
use windows::Win32::Foundation::{NTE_BAD_KEYSET, NTE_EXISTS, NTE_NOT_FOUND};
use windows::Win32::Security::Cryptography::{
    BCRYPT_ECCPUBLIC_BLOB, BCRYPT_ECDSA_PUBLIC_P256_MAGIC, CERT_KEY_SPEC, MS_KEY_STORAGE_PROVIDER,
    MS_PLATFORM_CRYPTO_PROVIDER, NCRYPT_ECDSA_P256_ALGORITHM, NCRYPT_FLAGS, NCRYPT_KEY_HANDLE,
    NCRYPT_PROV_HANDLE, NCRYPT_SILENT_FLAG, NCryptCreatePersistedKey, NCryptDeleteKey,
    NCryptExportKey, NCryptFinalizeKey, NCryptFreeObject, NCryptOpenKey, NCryptOpenStorageProvider,
    NCryptSignHash,
};
use windows_core::PCWSTR;

use crate::{Jwk, SecurityError, Signer};

/// Where a key lives.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Provider {
    /// The Microsoft Platform Crypto Provider: the TPM.
    Platform,
    /// The Microsoft Software Key Storage Provider: DPAPI-protected files in the user profile.
    Software,
}

impl Provider {
    fn name(self) -> PCWSTR {
        match self {
            Self::Platform => MS_PLATFORM_CRYPTO_PROVIDER,
            Self::Software => MS_KEY_STORAGE_PROVIDER,
        }
    }
}

/// An ECDSA P-256 key persisted by name for the current Windows user. The private key never
/// leaves the key storage provider and isn't exportable.
pub struct NcryptKey {
    handles: Handles,
    name: String,
    provider: Provider,
    jwk: Jwk,
    /// Serialises signing: key storage providers don't promise concurrent use of one handle.
    sign_lock: Mutex<()>,
}

/// An open key and its provider, freed in that order.
struct Handles {
    key: NCRYPT_KEY_HANDLE,
    provider: NCRYPT_PROV_HANDLE,
}

impl Drop for Handles {
    fn drop(&mut self) {
        if self.key.0 != 0 {
            // SAFETY: a non-zero key handle is one we opened and haven't freed or deleted.
            let _ = unsafe { NCryptFreeObject(self.key.into()) };
        }
        if self.provider.0 != 0 {
            // SAFETY: a non-zero provider handle is one we opened and haven't freed.
            let _ = unsafe { NCryptFreeObject(self.provider.into()) };
        }
    }
}

impl NcryptKey {
    /// Opens the key called `name`, creating it when it doesn't exist.
    ///
    /// With `prefer_tpm`, a key already in the TPM is used first; otherwise an existing software
    /// key is kept (so the device id doesn't change); otherwise a new key is created in the TPM,
    /// falling back to the software key storage provider when the TPM can't make one.
    pub fn open_or_create(name: &str, prefer_tpm: bool) -> Result<Self, SecurityError> {
        // A TPM that's missing or unusable is a reason to fall back, not an error.
        if prefer_tpm && let Ok(Some(key)) = Self::open(Provider::Platform, name) {
            return Ok(key);
        }
        if let Some(key) = Self::open(Provider::Software, name)? {
            return Ok(key);
        }
        if prefer_tpm && let Ok(key) = Self::create(Provider::Platform, name) {
            return Ok(key);
        }
        Self::create(Provider::Software, name)
    }

    /// The key's name.
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Deletes the key from its provider. Used by tests and by a device reset.
    pub fn delete(mut self) -> Result<(), SecurityError> {
        let key = std::mem::replace(&mut self.handles.key, NCRYPT_KEY_HANDLE(0));
        // No flags: the Platform Crypto Provider rejects NCRYPT_SILENT_FLAG here
        // (NTE_BAD_FLAGS), and our keys have no UI protection to suppress anyway.
        // SAFETY: `key` is our open key handle. On success NCryptDeleteKey also frees it; on
        // failure we leak it rather than risk freeing a handle the provider already released.
        unsafe { NCryptDeleteKey(key, 0) }
            .map_err(|e| SecurityError::platform("NCryptDeleteKey", e))
    }

    fn open(provider: Provider, name: &str) -> Result<Option<Self>, SecurityError> {
        let wide = to_wide(name);
        let mut handles = Handles {
            key: NCRYPT_KEY_HANDLE(0),
            provider: open_provider(provider)?,
        };
        // SAFETY: the provider handle is open, `wide` is a NUL-terminated UTF-16 string that
        // outlives the call, and `handles.key` is a writable handle slot.
        let opened = unsafe {
            NCryptOpenKey(
                handles.provider,
                &mut handles.key,
                PCWSTR(wide.as_ptr()),
                CERT_KEY_SPEC(0),
                NCRYPT_SILENT_FLAG,
            )
        };
        match opened {
            Ok(()) => Self::from_handles(handles, provider, name).map(Some),
            Err(e) if e.code() == NTE_BAD_KEYSET || e.code() == NTE_NOT_FOUND => Ok(None),
            Err(e) => Err(SecurityError::platform("NCryptOpenKey", e)),
        }
    }

    fn create(provider: Provider, name: &str) -> Result<Self, SecurityError> {
        let wide = to_wide(name);
        let mut handles = Handles {
            key: NCRYPT_KEY_HANDLE(0),
            provider: open_provider(provider)?,
        };
        // SAFETY: as in `open`; the algorithm id is a static NUL-terminated string.
        unsafe {
            NCryptCreatePersistedKey(
                handles.provider,
                &mut handles.key,
                NCRYPT_ECDSA_P256_ALGORITHM,
                PCWSTR(wide.as_ptr()),
                CERT_KEY_SPEC(0),
                NCRYPT_FLAGS(0),
            )
        }
        .map_err(|e| SecurityError::platform("NCryptCreatePersistedKey", e))?;
        // The default export policy is "not exportable", which is what we want.
        // SAFETY: `handles.key` is the unfinalised key just created.
        match unsafe { NCryptFinalizeKey(handles.key, NCRYPT_SILENT_FLAG) } {
            Ok(()) => Self::from_handles(handles, provider, name),
            // Another process created it first: use theirs.
            Err(e) if e.code() == NTE_EXISTS => {
                drop(handles);
                Self::open(provider, name)?
                    .ok_or_else(|| SecurityError::platform("NCryptFinalizeKey", e))
            }
            Err(e) => Err(SecurityError::platform("NCryptFinalizeKey", e)),
        }
    }

    fn from_handles(
        handles: Handles,
        provider: Provider,
        name: &str,
    ) -> Result<Self, SecurityError> {
        let jwk = export_public_jwk(handles.key)?;
        Ok(Self {
            handles,
            name: name.to_owned(),
            provider,
            jwk,
            sign_lock: Mutex::new(()),
        })
    }
}

impl std::fmt::Debug for NcryptKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("NcryptKey")
            .field("name", &self.name)
            .field("provider", &self.provider)
            .field("jwk", &self.jwk)
            .finish_non_exhaustive()
    }
}

impl Signer for NcryptKey {
    fn public_jwk(&self) -> Jwk {
        self.jwk.clone()
    }

    fn sign(&self, message: &[u8]) -> Result<[u8; 64], SecurityError> {
        let digest = Sha256::digest(message);
        let mut signature = [0u8; 64];
        let mut written = 0u32;
        let _guard = self
            .sign_lock
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        // SAFETY: the key handle is open for the life of `self`; the digest and signature
        // buffers are live slices and `written` is a writable u32.
        unsafe {
            NCryptSignHash(
                self.handles.key,
                None,
                &digest,
                Some(&mut signature),
                &mut written,
                NCRYPT_SILENT_FLAG,
            )
        }
        .map_err(|e| SecurityError::platform("NCryptSignHash", e))?;
        if written != 64 {
            return Err(SecurityError::InvalidKey(format!(
                "expected a 64-byte P-256 signature, got {written} bytes"
            )));
        }
        Ok(signature)
    }

    fn hardware_backed(&self) -> bool {
        self.provider == Provider::Platform
    }
}

fn open_provider(provider: Provider) -> Result<NCRYPT_PROV_HANDLE, SecurityError> {
    let mut handle = NCRYPT_PROV_HANDLE(0);
    // SAFETY: `handle` is a writable handle slot and the provider name is a static
    // NUL-terminated string.
    unsafe { NCryptOpenStorageProvider(&mut handle, provider.name(), 0) }
        .map_err(|e| SecurityError::platform("NCryptOpenStorageProvider", e))?;
    Ok(handle)
}

fn export_public_jwk(key: NCRYPT_KEY_HANDLE) -> Result<Jwk, SecurityError> {
    let mut size = 0u32;
    // SAFETY: a size query: no output buffer, `size` is a writable u32, `key` is open.
    unsafe {
        NCryptExportKey(
            key,
            None,
            BCRYPT_ECCPUBLIC_BLOB,
            None,
            None,
            &mut size,
            NCRYPT_FLAGS(0),
        )
    }
    .map_err(|e| SecurityError::platform("NCryptExportKey", e))?;
    let mut blob = vec![0u8; size as usize];
    // SAFETY: `blob` is a writable buffer of the size the provider asked for.
    unsafe {
        NCryptExportKey(
            key,
            None,
            BCRYPT_ECCPUBLIC_BLOB,
            None,
            Some(&mut blob),
            &mut size,
            NCRYPT_FLAGS(0),
        )
    }
    .map_err(|e| SecurityError::platform("NCryptExportKey", e))?;
    blob.truncate(size as usize);
    parse_ecc_public_blob(&blob)
}

/// Parses a `BCRYPT_ECCPUBLIC_BLOB`: `BCRYPT_ECCKEY_BLOB { dwMagic, cbKey }` (little-endian
/// u32s) followed by X and Y, each `cbKey` bytes, big-endian.
fn parse_ecc_public_blob(blob: &[u8]) -> Result<Jwk, SecurityError> {
    let invalid = |why: &str| SecurityError::InvalidKey(format!("ECCPUBLICBLOB: {why}"));
    let header = blob.get(..8).ok_or_else(|| invalid("too short"))?;
    let magic = u32::from_le_bytes([header[0], header[1], header[2], header[3]]);
    let key_len = u32::from_le_bytes([header[4], header[5], header[6], header[7]]) as usize;
    if magic != BCRYPT_ECDSA_PUBLIC_P256_MAGIC {
        return Err(invalid("not an ECDSA P-256 public key"));
    }
    if key_len != 32 || blob.len() != 8 + 2 * key_len {
        return Err(invalid("unexpected length"));
    }
    let (x, y) = blob[8..].split_at(key_len);
    Ok(Jwk::from_coordinates(x, y))
}

fn to_wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_an_ecc_public_blob() {
        let mut blob = BCRYPT_ECDSA_PUBLIC_P256_MAGIC.to_le_bytes().to_vec();
        blob.extend_from_slice(&32u32.to_le_bytes());
        blob.extend_from_slice(&[1u8; 32]);
        blob.extend_from_slice(&[2u8; 32]);
        let jwk = parse_ecc_public_blob(&blob).expect("parse");
        assert_eq!(jwk, Jwk::from_coordinates(&[1u8; 32], &[2u8; 32]));

        assert!(parse_ecc_public_blob(&blob[..40]).is_err());
        let mut wrong_magic = blob.clone();
        wrong_magic[0] ^= 1;
        assert!(parse_ecc_public_blob(&wrong_magic).is_err());
    }
}
