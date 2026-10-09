//! Canned answers for debug builds before the candidate sign-in API exists (`HV_DESKTOP_STUB=1`,
//! runbook). Any email signs in with the password `stub`; an email starting `new` asks for the
//! code `123456`. Release builds never use it.

use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use hv_api_client::auth::{Candidate, Interview, Organization};

use super::error::{CommandError, CommandResult};
use super::views::{ChecksSubmitted, ProfileView, SignInView};

pub const PASSWORD: &str = "stub";
pub const CODE: &str = "123456";
const CHALLENGE: &str = "stub-challenge";

#[derive(Default)]
pub struct Stub {
    email: Mutex<Option<String>>,
}

fn iso(at: SystemTime) -> String {
    let seconds = at
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_secs());
    let days = seconds / 86_400;
    let rest = seconds % 86_400;
    let (year, month, day) = civil_from_days(days as i64);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        (rest % 3600) / 60,
        rest % 60
    )
}

/// Days since 1970-01-01 to a calendar date (Howard Hinnant's algorithm).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let year = yoe + era * 400 + i64::from(month <= 2);
    (year, month, day)
}

fn profile(email: &str) -> ProfileView {
    let now = SystemTime::now();
    let hour = Duration::from_secs(3600);
    ProfileView {
        candidate: Candidate {
            id: "stub-candidate".into(),
            name: "Asha Rao".into(),
            email: email.into(),
            locale: "en-IN".into(),
        },
        organization: Organization {
            id: "stub-org".into(),
            name: "Acme (stub)".into(),
            support_email: Some("help@acme.example.test".into()),
        },
        interviews: vec![
            Interview {
                id: "00000000-0000-7000-8000-000000000001".into(),
                job_title: "Backend Engineer".into(),
                status: "invited".into(),
                starts_at: iso(now - hour),
                expires_at: iso(now + 24 * hour),
                duration_minutes: 45,
                third_eye: "optional".into(),
                proctoring_level: "standard".into(),
                coding: true,
            },
            Interview {
                id: "00000000-0000-7000-8000-000000000002".into(),
                job_title: "Data Engineer".into(),
                status: "invited".into(),
                starts_at: iso(now + 2 * hour),
                expires_at: iso(now + 26 * hour),
                duration_minutes: 30,
                third_eye: "required".into(),
                proctoring_level: "strict".into(),
                coding: false,
            },
        ],
    }
}

impl Stub {
    pub fn sign_in(&self, email: &str, password: &str) -> CommandResult<SignInView> {
        if password != PASSWORD {
            return Err(CommandError::new("invalid-credentials", None));
        }
        if let Ok(mut current) = self.email.lock() {
            *current = Some(email.to_owned());
        }
        if email.starts_with("new") {
            return Ok(SignInView::CodeRequired {
                challenge_id: CHALLENGE.into(),
                sent_to: "n***@example.test".into(),
            });
        }
        Ok(SignInView::Ok(profile(email)))
    }

    pub fn verify_code(&self, challenge_id: &str, code: &str) -> CommandResult<SignInView> {
        if challenge_id != CHALLENGE || code != CODE {
            return Err(CommandError::new("otp-invalid", None));
        }
        Ok(SignInView::Ok(profile(&self.email()?)))
    }

    pub fn profile(&self) -> CommandResult<ProfileView> {
        Ok(profile(&self.email()?))
    }

    pub fn sign_out(&self) {
        if let Ok(mut current) = self.email.lock() {
            *current = None;
        }
    }

    pub fn submit(&self, payload: &serde_json::Value) -> ChecksSubmitted {
        const MANDATORY: [&str; 4] = ["camera", "microphone", "screen_capture", "media_foundation"];
        let results = payload["results"].as_array().cloned().unwrap_or_default();
        let failed: Vec<String> = MANDATORY
            .iter()
            .filter(|name| {
                !results
                    .iter()
                    .any(|result| result["check"] == **name && result["status"] == "pass")
            })
            .map(|name| (*name).to_owned())
            .collect();
        ChecksSubmitted {
            id: "stub-checks".into(),
            passed: failed.is_empty(),
            failed_mandatory: failed,
        }
    }

    fn email(&self) -> CommandResult<String> {
        self.email
            .lock()
            .ok()
            .and_then(|current| current.clone())
            .ok_or_else(|| CommandError::new("signed-out", None))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signs_in_with_the_stub_password_and_asks_new_devices_for_a_code() {
        let stub = Stub::default();
        assert_eq!(
            stub.sign_in("asha@x.test", "nope").unwrap_err().code,
            "invalid-credentials"
        );
        assert!(matches!(
            stub.sign_in("asha@x.test", PASSWORD),
            Ok(SignInView::Ok(_))
        ));
        let SignInView::CodeRequired { challenge_id, .. } =
            stub.sign_in("new@x.test", PASSWORD).expect("a challenge")
        else {
            panic!("expected a code");
        };
        assert_eq!(
            stub.verify_code(&challenge_id, "000000").unwrap_err().code,
            "otp-invalid"
        );
        assert!(matches!(
            stub.verify_code(&challenge_id, CODE),
            Ok(SignInView::Ok(_))
        ));
        stub.sign_out();
        assert_eq!(stub.profile().unwrap_err().code, "signed-out");
    }

    #[test]
    fn passes_the_checks_only_when_every_mandatory_one_passed() {
        let stub = Stub::default();
        let passing = serde_json::json!({ "results": [
            { "check": "camera", "status": "pass" }, { "check": "microphone", "status": "pass" },
            { "check": "screen_capture", "status": "pass" }, { "check": "media_foundation", "status": "pass" }
        ]});
        assert!(stub.submit(&passing).passed);
        let failing = serde_json::json!({ "results": [{ "check": "camera", "status": "fail" }] });
        assert_eq!(stub.submit(&failing).failed_mandatory.len(), 4);
    }

    #[test]
    fn dates_are_iso_8601_in_utc() {
        assert_eq!(
            iso(UNIX_EPOCH + Duration::from_secs(1_760_000_000)),
            "2025-10-09T08:53:20Z"
        );
    }
}
