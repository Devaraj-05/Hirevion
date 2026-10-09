/// Everything that can go wrong with keys, proofs and the vault.
#[derive(Debug, thiserror::Error)]
pub enum SecurityError {
    /// A key or JWK that isn't a valid P-256 public or private key.
    #[error("invalid key: {0}")]
    InvalidKey(String),
    /// A signature that doesn't verify.
    #[error("the signature does not verify")]
    BadSignature,
    /// A DPoP proof that can't be parsed or has the wrong header.
    #[error("invalid DPoP proof: {0}")]
    InvalidProof(String),
    /// A vault name that isn't a plain file-name-safe token.
    #[error("invalid vault name {0:?}")]
    InvalidName(String),
    /// A Windows API call failed.
    #[error("{operation} failed: {message} (0x{code:08X})")]
    Platform {
        operation: &'static str,
        code: u32,
        message: String,
    },
    /// Reading or writing a vault file failed.
    #[error("vault I/O: {0}")]
    Io(#[from] std::io::Error),
    /// JSON encoding failed.
    #[error("encoding: {0}")]
    Encoding(String),
}

#[cfg(windows)]
impl SecurityError {
    pub(crate) fn platform(operation: &'static str, error: windows_core::Error) -> Self {
        Self::Platform {
            operation,
            // Bit-for-bit reinterpretation of the HRESULT, for display.
            code: error.code().0 as u32,
            message: error.message(),
        }
    }
}
