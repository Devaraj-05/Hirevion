use hv_security::SecurityError;

/// Everything an API call can fail with. Screens branch on [`ApiError::code`] only.
#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    /// The API answered with an error status. `code` is the problem's `code` member, or
    /// `http-<status>` when the body isn't a problem document (a proxy's HTML page, say).
    #[error("the API answered {status} {code}")]
    Problem {
        status: u16,
        code: String,
        detail: Option<String>,
        /// `Retry-After` in seconds, when the server sent one.
        retry_after: Option<u64>,
        /// The whole body: problem extensions such as `minimum_version` or `attempts_left`.
        /// A JSON string holding the raw text when the body isn't JSON, `null` when empty.
        body: serde_json::Value,
    },
    /// The request didn't get an answer: DNS, TLS, connection or timeout.
    #[error("network error: {0}")]
    Network(String),
    /// The answer wasn't what the contract says.
    #[error("unexpected response: {0}")]
    Decode(String),
    /// Signing, the vault, or a request that would leave the API origin.
    #[error("security error: {0}")]
    Security(String),
    /// There is no session: never signed in, signed out, or the refresh token was revoked.
    #[error("not signed in")]
    SignedOut,
}

impl ApiError {
    /// A stable code for every error: the problem's code, or `network`, `decode`, `security`,
    /// `signed-out`.
    pub fn code(&self) -> &str {
        match self {
            Self::Problem { code, .. } => code,
            Self::Network(_) => "network",
            Self::Decode(_) => "decode",
            Self::Security(_) => "security",
            Self::SignedOut => "signed-out",
        }
    }

    /// The HTTP status of a problem.
    pub fn status(&self) -> Option<u16> {
        match self {
            Self::Problem { status, .. } => Some(*status),
            _ => None,
        }
    }

    /// The `Retry-After` of a problem, in seconds.
    pub fn retry_after(&self) -> Option<u64> {
        match self {
            Self::Problem { retry_after, .. } => *retry_after,
            _ => None,
        }
    }

    /// Whether this is a problem with this code.
    pub fn is_problem(&self, code: &str) -> bool {
        matches!(self, Self::Problem { code: c, .. } if c == code)
    }
}

impl From<SecurityError> for ApiError {
    fn from(error: SecurityError) -> Self {
        Self::Security(error.to_string())
    }
}
