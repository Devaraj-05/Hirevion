//! The shape every check reports, shared with the webview and the API
//! (`docs/api/contracts/interview-session.md`, "System checks").

use serde::{Deserialize, Serialize};

/// A check's outcome. Serialised in lower case: `"pass"`, `"warn"`, `"fail"`, `"skipped"`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Pass,
    Warn,
    Fail,
    Skipped,
}

/// One check's result. `value` is what was measured ("6.1 GB free"); `detail` says what is
/// wrong and what to do about it. Both are left out of the JSON when absent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckResult {
    pub check: String,
    pub status: Status,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

impl CheckResult {
    #[must_use]
    pub fn new(check: &str, status: Status) -> Self {
        Self {
            check: check.to_owned(),
            status,
            value: None,
            detail: None,
        }
    }

    /// A check this build or platform doesn't run.
    #[must_use]
    pub fn skipped(check: &str, detail: &str) -> Self {
        Self::new(check, Status::Skipped).with_detail(detail)
    }

    #[must_use]
    pub fn with_value(mut self, value: impl Into<String>) -> Self {
        self.value = Some(value.into());
        self
    }

    #[must_use]
    pub fn with_detail(mut self, detail: impl Into<String>) -> Self {
        self.detail = Some(detail.into());
        self
    }
}

/// The check names this crate reports, as the API contract spells them.
pub mod names {
    pub const CPU: &str = "cpu";
    pub const MEMORY: &str = "memory";
    pub const DISK: &str = "disk";
    pub const DISPLAYS: &str = "displays";
    pub const PRIVACY: &str = "privacy";
    pub const MEDIA_FOUNDATION: &str = "media_foundation";
    /// Not a check of its own in the upload: its value becomes the payload's `os` field.
    pub const OS: &str = "os";
    pub const SCREEN_CAPTURE: &str = "screen_capture";
}

/// What [`crate::native_checks`] returns, in this order.
pub const NATIVE_CHECKS: [&str; 7] = [
    names::CPU,
    names::MEMORY,
    names::DISK,
    names::DISPLAYS,
    names::PRIVACY,
    names::MEDIA_FOUNDATION,
    names::OS,
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serialises_status_in_lower_case() {
        let statuses = [Status::Pass, Status::Warn, Status::Fail, Status::Skipped];
        let json = serde_json::to_string(&statuses).unwrap();
        assert_eq!(json, r#"["pass","warn","fail","skipped"]"#);
    }

    #[test]
    fn leaves_out_missing_value_and_detail() {
        let json = serde_json::to_string(&CheckResult::new("speaker", Status::Pass)).unwrap();
        assert_eq!(json, r#"{"check":"speaker","status":"pass"}"#);
    }

    #[test]
    fn writes_value_and_detail_when_present() {
        let result = CheckResult::new("memory", Status::Warn)
            .with_value("1.5 GB free")
            .with_detail("close apps");
        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(
            json,
            serde_json::json!({
                "check": "memory", "status": "warn", "value": "1.5 GB free", "detail": "close apps"
            })
        );
    }

    #[test]
    fn reads_results_with_or_without_the_optional_fields() {
        let bare: CheckResult =
            serde_json::from_str(r#"{"check":"third_eye","status":"skipped"}"#).unwrap();
        assert_eq!(bare, CheckResult::new("third_eye", Status::Skipped));
        let null_detail: CheckResult =
            serde_json::from_str(r#"{"check":"camera","status":"pass","value":"x","detail":null}"#)
                .unwrap();
        assert_eq!(
            null_detail,
            CheckResult::new("camera", Status::Pass).with_value("x")
        );
    }
}
