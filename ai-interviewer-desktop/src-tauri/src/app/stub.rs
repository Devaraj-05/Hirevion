//! Canned answers for debug builds without the API (`HV_DESKTOP_STUB=1`, runbook). Any email
//! signs in with the password `stub`; an email starting `new` asks for the code `123456`. The
//! interview runs in text mode with three canned questions. Release builds never use it.

use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use hv_api_client::auth::{Candidate, Interview, Organization};
use hv_system_check::{CheckResult, NATIVE_CHECKS, Status, names};

use serde_json::{Value, json};

use super::error::{CommandError, CommandResult};
use super::interview::InterviewAction;
use super::views::{ChecksSubmitted, ProfileView, SignInView};

pub const PASSWORD: &str = "stub";
pub const CODE: &str = "123456";
const CHALLENGE: &str = "stub-challenge";

#[derive(Default)]
pub struct Stub {
    email: Mutex<Option<String>>,
    answered: Mutex<usize>,
    /// `HV_DESKTOP_STUB_NATIVE=1`: the native system checks answer "pass" without touching the
    /// machine, so the end-to-end test runs the same on any runner.
    canned_native: bool,
}

const QUESTIONS: [&str; 3] = [
    "Tell me about a backend service you built and how you kept it reliable.",
    "How would you find out why an API endpoint became slow in production?",
    "Explain how you would design idempotent retries for a payment request.",
];
const PURPOSES: [&str; 10] = [
    "camera",
    "microphone",
    "screen",
    "audio",
    "video",
    "third_eye",
    "transcript",
    "coding_activity",
    "system_telemetry",
    "proctoring_events",
];

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
    pub fn from_env() -> Self {
        Self {
            canned_native: std::env::var("HV_DESKTOP_STUB_NATIVE").is_ok_and(|value| value == "1"),
            ..Self::default()
        }
    }

    /// The native checks (CPU, memory, …) as passes, or `None` to run the real ones.
    pub fn native_checks(&self) -> Option<Vec<CheckResult>> {
        self.canned_native.then(|| {
            NATIVE_CHECKS
                .iter()
                .map(|check| CheckResult::new(check, Status::Pass).with_value("stub"))
                .collect()
        })
    }

    /// The screen-capture probe as a pass, or `None` to run the real one.
    pub fn screen_capture(&self) -> Option<CheckResult> {
        self.canned_native
            .then(|| CheckResult::new(names::SCREEN_CAPTURE, Status::Pass).with_value("stub"))
    }

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

    /// The interview calls in text mode (contract interview-session), without LiveKit.
    pub fn interview(
        &self,
        interview_id: &str,
        action: InterviewAction,
        body: Option<&Value>,
    ) -> CommandResult<Value> {
        self.email()?;
        let answered = || self.answered.lock().map_or(0, |count| *count);
        let state = |answered: usize| {
            let question = QUESTIONS.get(answered).map(|text| {
                json!({ "id": format!("stub-q{answered}"), "index": answered + 1, "text": text,
                        "type": "technical", "time_limit_seconds": 300, "workspace": "none", "languages": [] })
            });
            json!({ "state": {
                "status": if question.is_some() { "in_progress" } else { "completed" },
                "remaining_seconds": 2700 - 300 * answered,
                "third_eye": "optional", "workspace": "none", "answer_mode": "text",
                "question": question,
                "voice": if question.is_some() { "waiting" } else { "ended" },
                "stage": if question.is_some() { "medium" } else { "completion" },
                "message": question.as_ref().map(|q| q["text"].clone()),
                "notice": null
            }})
        };
        Ok(match action {
            InterviewAction::Briefing => json!({
                "instructions": [
                    "Find a quiet, well-lit room and sit facing your camera.",
                    "Close other apps; only this app may be open during the interview.",
                    "Keep your face visible and stay in front of the screen.",
                    "Speak clearly and take a moment to think when you need it.",
                    "Don't use notes, other people or other devices unless allowed.",
                    "If you lose your connection, open the app again to resume."
                ],
                "mandatory_checks": ["camera", "microphone", "screen_capture", "media_foundation"],
                "notice": { "version": "stub-2026-10-10", "items": PURPOSES.iter().map(|purpose| json!({
                    "purpose": purpose,
                    "text": format!("We record {} during the interview for review.", purpose.replace('_', " ")),
                    "required": *purpose != "third_eye" && *purpose != "coding_activity"
                })).collect::<Vec<_>>() },
                "accommodations": { "requested": [], "approved": [] },
                "answer_mode": "text",
                "third_eye": "optional"
            }),
            InterviewAction::SystemChecks => {
                serde_json::to_value(self.submit(body.unwrap_or(&Value::Null)))
                    .map_err(|error| CommandError::new("unexpected-response", error.to_string()))?
            }
            InterviewAction::Consents => {
                json!({ "id": "stub-consent", "complete": true, "missing": [] })
            }
            InterviewAction::Accommodations => {
                json!({ "id": "stub-accommodation", "status": "requested" })
            }
            InterviewAction::Start => {
                let mut answer = state(answered());
                answer["livekit_url"] = Value::Null;
                answer["room"] = json!(format!("iv-{interview_id}"));
                answer
            }
            InterviewAction::Session => state(answered()),
            InterviewAction::Answer => {
                if let Ok(mut count) = self.answered.lock() {
                    *count = (*count + 1).min(QUESTIONS.len());
                }
                state(answered())
            }
            InterviewAction::Workspace => Value::Null,
            InterviewAction::Complete => {
                if let Ok(mut count) = self.answered.lock() {
                    *count = 0;
                }
                json!({ "status": "completed" })
            }
        })
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
    fn canned_native_checks_are_opt_in_and_cover_the_mandatory_ones() {
        assert!(Stub::default().native_checks().is_none());
        assert!(Stub::default().screen_capture().is_none());
        let stub = Stub {
            canned_native: true,
            ..Stub::default()
        };
        let native = stub.native_checks().expect("canned checks");
        assert_eq!(native.len(), NATIVE_CHECKS.len());
        assert!(native.iter().all(|result| result.status == Status::Pass));
        let mut all: Vec<_> = native
            .iter()
            .map(|result| serde_json::json!({ "check": result.check, "status": "pass" }))
            .collect();
        all.extend(
            ["camera", "microphone"]
                .map(|name| serde_json::json!({ "check": name, "status": "pass" })),
        );
        all.push(serde_json::json!({ "check": "screen_capture", "status": "pass" }));
        assert!(stub.screen_capture().is_some());
        assert!(stub.submit(&serde_json::json!({ "results": all })).passed);
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
    fn runs_a_text_mode_interview_to_the_end() {
        let stub = Stub::default();
        assert_eq!(
            stub.interview("iv", InterviewAction::Briefing, None)
                .unwrap_err()
                .code,
            "signed-out"
        );
        stub.sign_in("asha@x.test", PASSWORD).expect("signed in");
        let briefing = stub
            .interview("iv", InterviewAction::Briefing, None)
            .expect("briefing");
        assert_eq!(
            briefing["notice"]["items"].as_array().map(Vec::len),
            Some(10)
        );
        let started = stub
            .interview("iv", InterviewAction::Start, None)
            .expect("start");
        assert_eq!(started["state"]["question"]["index"], 1);
        let mut state = started;
        for _ in 0..QUESTIONS.len() {
            state = stub
                .interview(
                    "iv",
                    InterviewAction::Answer,
                    Some(&json!({ "text": "an answer" })),
                )
                .expect("answer");
        }
        assert_eq!(state["state"]["status"], "completed");
        assert!(state["state"]["question"].is_null());
    }

    #[test]
    fn dates_are_iso_8601_in_utc() {
        assert_eq!(
            iso(UNIX_EPOCH + Duration::from_secs(1_760_000_000)),
            "2025-10-09T08:53:20Z"
        );
    }
}
