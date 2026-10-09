//! Per-file facts that are slow to compute (SHA-256, signature), cached by path, size and
//! modification time, so a file is only read again when it changes.

use std::collections::HashMap;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

#[cfg(not(windows))]
use sha2::{Digest, Sha256};

use crate::observation::SignatureInfo;

/// What is known about one executable file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileFacts {
    pub sha256: Option<String>,
    pub signature: SignatureInfo,
}

/// Facts per file, recomputed when the size or modification time changes.
pub struct FileCache {
    entries: HashMap<PathBuf, (u64, Option<SystemTime>, FileFacts)>,
    signature: Box<dyn FnMut(&Path) -> SignatureInfo + Send>,
}

impl std::fmt::Debug for FileCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FileCache")
            .field("entries", &self.entries.len())
            .finish_non_exhaustive()
    }
}

impl FileCache {
    /// A cache that checks signatures with `signature`.
    pub fn new(signature: impl FnMut(&Path) -> SignatureInfo + Send + 'static) -> Self {
        Self {
            entries: HashMap::new(),
            signature: Box::new(signature),
        }
    }

    /// The facts for `path`: from the cache when the file is unchanged.
    pub fn facts(&mut self, path: &Path) -> FileFacts {
        let Ok(metadata) = std::fs::metadata(path) else {
            return FileFacts {
                sha256: None,
                signature: SignatureInfo::default(),
            };
        };
        let size = metadata.len();
        let modified = metadata.modified().ok();
        if let Some((s, m, facts)) = self.entries.get(path)
            && *s == size
            && *m == modified
        {
            return facts.clone();
        }
        let facts = FileFacts {
            sha256: sha256_file(path).ok(),
            signature: (self.signature)(path),
        };
        self.entries
            .insert(path.to_owned(), (size, modified, facts.clone()));
        facts
    }

    /// How many files are cached.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

/// Lower-case hex SHA-256 of a file's contents.
///
/// On Windows this uses CNG (`BCryptHashData`, SHA-NI where the processor has it): executables
/// run to hundreds of megabytes, and a newly started one must be identified within the SP-11
/// bound of 2 s whatever the build profile.
pub fn sha256_file(path: &Path) -> std::io::Result<String> {
    let mut file = std::fs::File::open(path)?;
    let mut hasher = FileHasher::new()?;
    let mut buffer = vec![0u8; 1024 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read])?;
    }
    Ok(hex(&hasher.finish()?))
}

#[cfg(not(windows))]
struct FileHasher(Sha256);

#[cfg(not(windows))]
impl FileHasher {
    fn new() -> std::io::Result<Self> {
        Ok(Self(Sha256::new()))
    }

    fn update(&mut self, bytes: &[u8]) -> std::io::Result<()> {
        self.0.update(bytes);
        Ok(())
    }

    fn finish(self) -> std::io::Result<Vec<u8>> {
        Ok(self.0.finalize().to_vec())
    }
}

#[cfg(windows)]
struct FileHasher(windows::Win32::Security::Cryptography::BCRYPT_HASH_HANDLE);

#[cfg(windows)]
impl FileHasher {
    fn new() -> std::io::Result<Self> {
        use windows::Win32::Security::Cryptography::{
            BCRYPT_HASH_HANDLE, BCRYPT_SHA256_ALG_HANDLE, BCryptCreateHash,
        };
        let mut handle = BCRYPT_HASH_HANDLE::default();
        // SAFETY: the SHA-256 pseudo-handle needs no opening; `handle` is a live
        // out-parameter, and CNG allocates the hash object itself (no buffer passed).
        unsafe { BCryptCreateHash(BCRYPT_SHA256_ALG_HANDLE, &raw mut handle, None, None, 0) }
            .ok()
            .map_err(std::io::Error::other)?;
        Ok(Self(handle))
    }

    fn update(&mut self, bytes: &[u8]) -> std::io::Result<()> {
        use windows::Win32::Security::Cryptography::BCryptHashData;
        // SAFETY: the hash handle is open and `bytes` is a live slice.
        unsafe { BCryptHashData(self.0, bytes, 0) }
            .ok()
            .map_err(std::io::Error::other)
    }

    fn finish(self) -> std::io::Result<Vec<u8>> {
        use windows::Win32::Security::Cryptography::BCryptFinishHash;
        let mut digest = vec![0u8; 32];
        // SAFETY: the hash handle is open and `digest` is the 32 bytes SHA-256 produces.
        unsafe { BCryptFinishHash(self.0, &mut digest, 0) }
            .ok()
            .map_err(std::io::Error::other)?;
        Ok(digest)
    }
}

#[cfg(windows)]
impl Drop for FileHasher {
    fn drop(&mut self) {
        use windows::Win32::Security::Cryptography::BCryptDestroyHash;
        // SAFETY: the handle came from BCryptCreateHash and is destroyed once.
        let _ = unsafe { BCryptDestroyHash(self.0) };
    }
}

/// Lower-case hex.
pub fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    bytes
        .iter()
        .fold(String::with_capacity(bytes.len() * 2), |mut s, b| {
            let _ = write!(s, "{b:02x}");
            s
        })
}
