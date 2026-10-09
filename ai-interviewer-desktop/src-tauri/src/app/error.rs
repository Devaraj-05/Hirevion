//! What a failed command tells the webview: a stable `code` it translates, a `detail` for
//! diagnostics, and the problem's extra fields (`minimum_version`, `attempts_left`, …).

use hv_api_client::ApiError;
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CommandError {
    pub code: String,
    pub detail: Option<String>,
    pub extra: serde_json::Value,
}

impl CommandError {
    pub fn new(code: &str, detail: impl Into<Option<String>>) -> Self {
        Self {
            code: code.to_owned(),
            detail: detail.into(),
            extra: serde_json::Value::Null,
        }
    }
}

impl From<ApiError> for CommandError {
    fn from(error: ApiError) -> Self {
        match error {
            ApiError::Problem {
                code, detail, body, ..
            } => Self {
                code,
                detail,
                extra: body,
            },
            ApiError::Network(detail) => Self::new("network", detail),
            ApiError::Decode(detail) => Self::new("unexpected-response", detail),
            ApiError::Security(detail) => Self::new("security", detail),
            ApiError::SignedOut => Self::new("signed-out", None),
        }
    }
}

pub type CommandResult<T> = Result<T, CommandError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_problem_keeps_its_code_and_extra_fields() {
        let error = CommandError::from(ApiError::Problem {
            status: 426,
            code: "app-update-required".into(),
            detail: Some("Update".into()),
            retry_after: None,
            body: serde_json::json!({ "minimum_version": "2.0.0" }),
        });
        assert_eq!(error.code, "app-update-required");
        assert_eq!(error.extra["minimum_version"], "2.0.0");
    }

    #[test]
    fn transport_failures_get_codes_the_screens_know() {
        assert_eq!(
            CommandError::from(ApiError::Network("dns".into())).code,
            "network"
        );
        assert_eq!(CommandError::from(ApiError::SignedOut).code, "signed-out");
    }
}
