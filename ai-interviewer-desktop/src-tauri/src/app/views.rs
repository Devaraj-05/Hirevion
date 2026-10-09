//! What the commands hand the webview. Tokens never appear here (ADR-0018): the sign-in
//! results drop them before anything crosses to JavaScript.

use hv_api_client::auth::{
    Candidate, Interview, LoginOutcome, Me, Organization, ReleaseCheck, ReleaseStatus,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize)]
pub struct AppInfoView {
    pub version: String,
    pub channel: String,
    pub arch: String,
    pub os: String,
    pub debug: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ReleaseView {
    pub status: &'static str,
    pub latest_version: Option<String>,
    pub minimum_version: Option<String>,
    pub download_url: Option<String>,
}

impl From<ReleaseCheck> for ReleaseView {
    fn from(check: ReleaseCheck) -> Self {
        Self {
            status: match check.status {
                ReleaseStatus::Ok => "ok",
                ReleaseStatus::UpdateAvailable => "update-available",
                ReleaseStatus::UpdateRequired => "update-required",
            },
            latest_version: check.latest.map(|latest| latest.version),
            minimum_version: Some(check.minimum_version),
            download_url: check.download_url,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ProfileView {
    pub candidate: Candidate,
    pub organization: Organization,
    pub interviews: Vec<Interview>,
}

impl From<Me> for ProfileView {
    fn from(me: Me) -> Self {
        Self {
            candidate: me.candidate,
            organization: me.organization,
            interviews: me.interviews,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum SignInView {
    Ok(ProfileView),
    CodeRequired {
        challenge_id: String,
        sent_to: String,
    },
}

impl From<LoginOutcome> for SignInView {
    fn from(outcome: LoginOutcome) -> Self {
        match outcome {
            LoginOutcome::Ok(signed_in) => {
                let signed_in = *signed_in;
                Self::Ok(ProfileView {
                    candidate: signed_in.candidate,
                    organization: signed_in.organization,
                    interviews: signed_in.interviews,
                })
            }
            LoginOutcome::OtpRequired(challenge) => Self::CodeRequired {
                challenge_id: challenge.challenge_id,
                sent_to: challenge.sent_to,
            },
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RoundTripView {
    pub rtt_ms: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChecksSubmitted {
    pub id: String,
    pub passed: bool,
    pub failed_mandatory: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signing_in_never_hands_tokens_to_the_webview() {
        let outcome: LoginOutcome = serde_json::from_value(serde_json::json!({
            "status": "ok",
            "access_token": "secret-access",
            "token_type": "DPoP",
            "expires_in": 600,
            "refresh_token": "secret-refresh",
            "refresh_expires_in": 28800,
            "candidate": { "id": "c", "name": "Asha", "email": "a@x.test", "locale": "en-IN" },
            "organization": { "id": "o", "name": "Acme", "support_email": null },
            "interviews": []
        }))
        .expect("a sign-in answer");
        let shown = serde_json::to_string(&SignInView::from(outcome)).expect("serialises");
        assert!(!shown.contains("secret"), "{shown}");
        assert!(shown.contains("\"status\":\"ok\""));
    }

    #[test]
    fn a_new_device_asks_for_the_code() {
        let outcome: LoginOutcome = serde_json::from_value(serde_json::json!({
            "status": "otp_required", "challenge_id": "ch", "sent_to": "a***@x.test", "expires_in": 600
        }))
        .expect("a challenge");
        assert_eq!(
            serde_json::to_value(SignInView::from(outcome)).expect("serialises"),
            serde_json::json!({ "status": "code_required", "challenge_id": "ch", "sent_to": "a***@x.test" })
        );
    }
}
