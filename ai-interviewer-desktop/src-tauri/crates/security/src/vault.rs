use std::io::Write as _;
use std::path::{Path, PathBuf};

use crate::SecurityError;

/// Small secrets on disk, one file per name, sealed with DPAPI for the current Windows user.
///
/// The app points it at `%LOCALAPPDATA%\Hirevion\vault`; it holds only the refresh token.
/// Writes go to a temporary file that is then renamed over the old one, so a crash never leaves
/// a half-written secret.
#[derive(Debug, Clone)]
pub struct Vault {
    dir: PathBuf,
}

/// The file extension of a sealed secret.
const EXTENSION: &str = "secret";

impl Vault {
    /// A vault in `dir`. The directory is created on the first write.
    pub fn new(dir: impl Into<PathBuf>) -> Self {
        Self { dir: dir.into() }
    }

    /// The vault's directory.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    /// Seals and stores `secret` under `name`, replacing any previous value.
    pub fn put(&self, name: &str, secret: &[u8]) -> Result<(), SecurityError> {
        let path = self.path(name)?;
        let sealed = seal::protect(secret)?;
        std::fs::create_dir_all(&self.dir)?;
        // A leading dot keeps temporary names out of the valid-name space.
        let temp = self
            .dir
            .join(format!(".{name}.{}.tmp", uuid::Uuid::new_v4().simple()));
        let written = (|| {
            let mut file = std::fs::File::create(&temp)?;
            file.write_all(&sealed)?;
            file.sync_all()?;
            drop(file);
            std::fs::rename(&temp, &path)
        })();
        if let Err(error) = written {
            let _ = std::fs::remove_file(&temp);
            return Err(error.into());
        }
        Ok(())
    }

    /// The secret stored under `name`, or `None` when there is none.
    ///
    /// A file that can't be unsealed (tampered with, or from another Windows user) is an error.
    pub fn get(&self, name: &str) -> Result<Option<Vec<u8>>, SecurityError> {
        let path = self.path(name)?;
        match std::fs::read(&path) {
            Ok(sealed) => seal::unprotect(&sealed).map(Some),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    /// Removes the secret stored under `name`. Removing a missing secret is not an error.
    pub fn delete(&self, name: &str) -> Result<(), SecurityError> {
        let path = self.path(name)?;
        match std::fs::remove_file(&path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error.into()),
        }
    }

    fn path(&self, name: &str) -> Result<PathBuf, SecurityError> {
        let valid = (1..=64).contains(&name.len())
            && name.starts_with(|c: char| c.is_ascii_alphanumeric())
            && name
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'));
        if !valid {
            return Err(SecurityError::InvalidName(name.to_owned()));
        }
        Ok(self.dir.join(format!("{name}.{EXTENSION}")))
    }
}

/// DPAPI (`CryptProtectData`) for the current user, with fixed entropy and no UI.
#[cfg(windows)]
mod seal {
    use windows::Win32::Foundation::{HLOCAL, LocalFree};
    use windows::Win32::Security::Cryptography::{
        CRYPT_INTEGER_BLOB, CRYPTPROTECT_UI_FORBIDDEN, CryptProtectData, CryptUnprotectData,
    };

    use crate::SecurityError;

    /// Extra entropy bound into every blob, so other DPAPI users of this account can't
    /// unseal our files by accident.
    const ENTROPY: &[u8] = b"Hirevion vault v1";

    pub(super) fn protect(plain: &[u8]) -> Result<Vec<u8>, SecurityError> {
        let input = blob(plain)?;
        let entropy = blob(ENTROPY)?;
        let mut output = CRYPT_INTEGER_BLOB::default();
        // SAFETY: `input` and `entropy` point at live slices of the stated lengths that DPAPI
        // only reads; `output` is a writable blob that DPAPI fills with a LocalAlloc buffer.
        unsafe {
            CryptProtectData(
                &input,
                windows_core::w!("Hirevion vault"),
                Some(&entropy),
                None,
                None,
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        }
        .map_err(|e| SecurityError::platform("CryptProtectData", e))?;
        // SAFETY: the call succeeded, so `output` is a DPAPI-allocated buffer we now own.
        Ok(unsafe { take(output, false) })
    }

    pub(super) fn unprotect(sealed: &[u8]) -> Result<Vec<u8>, SecurityError> {
        let input = blob(sealed)?;
        let entropy = blob(ENTROPY)?;
        let mut output = CRYPT_INTEGER_BLOB::default();
        // SAFETY: as in `protect`: read-only inputs of the stated lengths, a writable output.
        unsafe {
            CryptUnprotectData(
                &input,
                None,
                Some(&entropy),
                None,
                None,
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        }
        .map_err(|e| SecurityError::platform("CryptUnprotectData", e))?;
        // SAFETY: the call succeeded, so `output` is a DPAPI-allocated buffer we now own.
        Ok(unsafe { take(output, true) })
    }

    fn blob(data: &[u8]) -> Result<CRYPT_INTEGER_BLOB, SecurityError> {
        let len = u32::try_from(data.len()).map_err(|_| SecurityError::Platform {
            operation: "DPAPI",
            code: 0,
            message: "secret too large".into(),
        })?;
        Ok(CRYPT_INTEGER_BLOB {
            cbData: len,
            // DPAPI never writes through input blobs; the API just isn't const-correct.
            pbData: data.as_ptr().cast_mut(),
        })
    }

    /// Copies a DPAPI output blob into a Vec, optionally wipes it, and frees it.
    ///
    /// # Safety
    /// `blob` must be an output of a successful CryptProtectData/CryptUnprotectData call that
    /// hasn't been freed yet.
    unsafe fn take(blob: CRYPT_INTEGER_BLOB, wipe: bool) -> Vec<u8> {
        if blob.pbData.is_null() {
            return Vec::new();
        }
        let len = blob.cbData as usize;
        // SAFETY: per the contract, DPAPI allocated `cbData` initialised bytes at `pbData`.
        let data = unsafe { std::slice::from_raw_parts(blob.pbData, len) }.to_vec();
        if wipe {
            // SAFETY: the same live, writable allocation of `len` bytes.
            unsafe { std::ptr::write_bytes(blob.pbData, 0, len) };
        }
        // SAFETY: DPAPI output buffers are allocated with LocalAlloc and freed with LocalFree,
        // exactly once, here.
        unsafe { LocalFree(Some(HLOCAL(blob.pbData.cast()))) };
        data
    }
}

/// NOT A SECURE STORE. The desktop app ships for Windows only; this plain pass-through exists
/// solely so the crate builds and its tests run on non-Windows CI hosts.
#[cfg(not(windows))]
mod seal {
    use crate::SecurityError;

    pub(super) fn protect(plain: &[u8]) -> Result<Vec<u8>, SecurityError> {
        Ok(plain.to_vec())
    }

    pub(super) fn unprotect(sealed: &[u8]) -> Result<Vec<u8>, SecurityError> {
        Ok(sealed.to_vec())
    }
}
