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
use super::third_eye::{PairingView, issued_view, status_view};
use super::views::{ChecksSubmitted, ProfileView, SignInView};

pub const PASSWORD: &str = "stub";
pub const CODE: &str = "123456";
const CHALLENGE: &str = "stub-challenge";

#[derive(Default)]
pub struct Stub {
    email: Mutex<Option<String>>,
    answered: Mutex<usize>,
    /// When the coding question was first served, and its last saved draft.
    coding_asked_at: Mutex<Option<SystemTime>>,
    coding_draft: Mutex<Option<Value>>,
    /// Status reads since the third eye's code was issued: a stub phone scans it on the second
    /// and connects on the third.
    third_eye_polls: Mutex<usize>,
    /// `HV_DESKTOP_STUB_NATIVE=1`: the native system checks answer "pass" without touching the
    /// machine, so the end-to-end test runs the same on any runner.
    canned_native: bool,
}

struct StubQuestion {
    text: &'static str,
    /// `code` for the coding console, `none` otherwise.
    workspace: &'static str,
    languages: &'static [&'static str],
}

const QUESTIONS: [StubQuestion; 4] = [
    StubQuestion {
        text: "Tell me about a backend service you built and how you kept it reliable.",
        workspace: "none",
        languages: &[],
    },
    StubQuestion {
        text: "Write a function two_sum(nums, target) that returns the indexes of the two numbers \
               in nums that add up to target. Type it in the box, choose its language and submit.",
        workspace: "code",
        languages: &["python", "javascript"],
    },
    StubQuestion {
        text: "How would you find out why an API endpoint became slow in production?",
        workspace: "none",
        languages: &[],
    },
    StubQuestion {
        text: "Explain how you would design idempotent retries for a payment request.",
        workspace: "none",
        languages: &[],
    },
];
const CODING_LIMIT_SECONDS: u64 = 600;
const STUB_PAIRING: &str = "00000000-0000-7000-8000-0000000000e1";
/// The server's limit on code and drafts (256 KB of UTF-8).
const MAX_CODE_BYTES: usize = 256 * 1024;
const TELEMETRY_KINDS: [&str; 7] = [
    "typing_started",
    "typing_stopped",
    "paste",
    "copy",
    "cut",
    "focus",
    "blur",
];

fn starter_code(language: &str) -> &'static str {
    match language {
        "python" => "def two_sum(nums, target):\n    pass\n",
        "javascript" => "function twoSum(nums, target) {\n}\n",
        _ => "",
    }
}

fn question_id(index: usize) -> String {
    format!("stub-q{index}")
}

/// One integrity event as the server accepts it: a known kind, a time, and a length for the
/// clipboard kinds only. Anything else (text above all) is refused.
fn valid_event(event: &Value) -> bool {
    let Some(fields) = event.as_object() else {
        return false;
    };
    let kind = fields
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let clipboard = matches!(kind, "paste" | "copy" | "cut");
    TELEMETRY_KINDS.contains(&kind)
        && fields.get("at").is_some_and(Value::is_string)
        && fields
            .keys()
            .all(|key| key == "kind" || key == "at" || (clipboard && key == "chars"))
        && (!clipboard || fields.get("chars").is_some_and(Value::is_u64))
}
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
        let state =
            |answered: usize| {
                let question = QUESTIONS.get(answered).map(|question| {
                let limit = if question.workspace == "code" { CODING_LIMIT_SECONDS } else { 300 };
                json!({ "id": question_id(answered), "index": answered + 1, "text": question.text,
                        "type": "technical", "time_limit_seconds": limit,
                        "workspace": question.workspace, "languages": question.languages })
            });
                json!({ "state": {
                    "status": if question.is_some() { "in_progress" } else { "completed" },
                    "remaining_seconds": 2700 - 300 * answered,
                    "third_eye": "optional", "answer_mode": "text",
                    "workspace": QUESTIONS.get(answered).map_or("none", |q| q.workspace),
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
                self.advance();
                state(answered())
            }
            InterviewAction::Workspace => {
                let body = body.unwrap_or(&Value::Null);
                if !self.is_coding_question(body["question_id"].as_str()) {
                    return Err(CommandError::new("question-not-found", None));
                }
                let content = body["content"].as_str().unwrap_or_default();
                if content.len() > MAX_CODE_BYTES {
                    return Err(CommandError::new("workspace-too-large", None));
                }
                if let Ok(mut draft) = self.coding_draft.lock() {
                    *draft = Some(json!({ "language": body["language"], "content": content,
                                          "saved_at": iso(SystemTime::now()) }));
                }
                Value::Null
            }
            InterviewAction::Coding => {
                let index = answered();
                match QUESTIONS.get(index) {
                    Some(question) if question.workspace == "code" => {
                        json!({ "question": self.coding_question(index, question) })
                    }
                    _ => json!({ "question": null }),
                }
            }
            InterviewAction::CodingSubmit => {
                let body = body.unwrap_or(&Value::Null);
                let index = answered();
                let current = QUESTIONS
                    .get(index)
                    .filter(|question| question.workspace == "code");
                let Some(question) = current
                    .filter(|_| body["question_id"].as_str() == Some(question_id(index).as_str()))
                else {
                    return Err(CommandError::new("question-not-current", None));
                };
                let language = body["language"].as_str().unwrap_or_default();
                if !question.languages.contains(&language) {
                    return Err(CommandError::new("language-not-offered", None));
                }
                let code = body["code"].as_str().unwrap_or_default();
                if code.len() > MAX_CODE_BYTES {
                    return Err(CommandError::new("code-too-large", None));
                }
                self.advance();
                json!({
                    // The stub doesn't hash the code; the server stores its SHA-256.
                    "submission": { "id": "stub-submission", "question_id": question_id(index),
                                    "language": language, "size": code.len(), "sha256": null,
                                    "source": "submitted", "submitted_at": iso(SystemTime::now()) },
                    "state": state(answered())["state"]
                })
            }
            InterviewAction::CodingTelemetry => {
                let body = body.unwrap_or(&Value::Null);
                if !self.is_coding_question(body["question_id"].as_str()) {
                    return Err(CommandError::new("question-not-found", None));
                }
                let events = body["events"].as_array().cloned().unwrap_or_default();
                // The server's schema takes 1 to 200 events.
                if events.is_empty() {
                    return Err(CommandError::new("validation-failed", None));
                }
                if events.len() > 200 {
                    return Err(CommandError::new("too-many-events", None));
                }
                if !events.iter().all(valid_event) {
                    return Err(CommandError::new("unknown-event", None));
                }
                json!({ "accepted": events.len() })
            }
            InterviewAction::Complete => {
                if let Ok(mut count) = self.answered.lock() {
                    *count = 0;
                }
                self.reset_coding();
                json!({ "status": "completed" })
            }
        })
    }

    /// Closes the open question (an answer or a submission) and moves to the next one.
    fn advance(&self) {
        if let Ok(mut count) = self.answered.lock() {
            *count = (*count + 1).min(QUESTIONS.len());
        }
    }

    fn reset_coding(&self) {
        if let Ok(mut asked) = self.coding_asked_at.lock() {
            *asked = None;
        }
        if let Ok(mut draft) = self.coding_draft.lock() {
            *draft = None;
        }
    }

    /// Whether `id` names the stub's coding question, open or closed (the server takes late
    /// drafts and events for any question of the interview).
    fn is_coding_question(&self, id: Option<&str>) -> bool {
        QUESTIONS.iter().enumerate().any(|(index, question)| {
            question.workspace == "code" && id == Some(question_id(index).as_str())
        })
    }

    /// `GET /coding`'s question: its languages and starter code, when it was asked (the first
    /// time it was served), and the last saved draft.
    fn coding_question(&self, index: usize, question: &StubQuestion) -> Value {
        let asked_at = self
            .coding_asked_at
            .lock()
            .map(|mut asked| *asked.get_or_insert_with(SystemTime::now))
            .unwrap_or_else(|_| SystemTime::now());
        let starters: serde_json::Map<String, Value> = question
            .languages
            .iter()
            .map(|language| ((*language).to_owned(), json!(starter_code(language))))
            .collect();
        let draft = self
            .coding_draft
            .lock()
            .ok()
            .and_then(|draft| draft.clone())
            .unwrap_or(Value::Null);
        json!({ "question_id": question_id(index), "text": question.text,
                "languages": question.languages, "starter_code": starters,
                "time_limit_seconds": CODING_LIMIT_SECONDS, "asked_at": iso(asked_at),
                "draft": draft })
    }

    /// A code for the stub's phone step (a fresh pairing each time).
    pub fn third_eye_pair(&self) -> CommandResult<PairingView> {
        self.email()?;
        if let Ok(mut polls) = self.third_eye_polls.lock() {
            *polls = 0;
        }
        issued_view(&json!({
            "pairing_id": STUB_PAIRING,
            "qr_url": "https://eye.hirevion.localhost/#t=stub-pairing-token",
            "expires_at": iso(SystemTime::now() + Duration::from_secs(120)),
            "status": "issued"
        }))
    }

    /// The stub phone: the code waits, is scanned, then the camera connects.
    pub fn third_eye_status(&self) -> CommandResult<PairingView> {
        self.email()?;
        let polls = self.third_eye_polls.lock().map_or(3, |mut polls| {
            *polls += 1;
            *polls
        });
        let (status, device) = match polls {
            1 => ("issued", Value::Null),
            2 => ("redeemed", Value::Null),
            _ => (
                "connected",
                json!({ "platform": "Android 15 Chrome (stub)" }),
            ),
        };
        Ok(status_view(
            STUB_PAIRING,
            &json!({ "status": status, "device": device }),
        ))
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
    fn serves_a_coding_question_keeps_its_drafts_and_takes_one_submission() {
        let stub = Stub::default();
        stub.sign_in("asha@x.test", PASSWORD).expect("signed in");
        let start = stub
            .interview("iv", InterviewAction::Start, None)
            .expect("start");
        assert_eq!(start["state"]["question"]["workspace"], "none");
        let none = stub
            .interview("iv", InterviewAction::Coding, None)
            .expect("coding");
        assert!(
            none["question"].is_null(),
            "the open question isn't a coding one"
        );

        // The second question is the coding one.
        let state = stub
            .interview(
                "iv",
                InterviewAction::Answer,
                Some(&json!({ "text": "an answer" })),
            )
            .expect("answer");
        let asked = &state["state"]["question"];
        assert_eq!(asked["workspace"], "code");
        assert_eq!(
            state["state"]["workspace"], "code",
            "the state names the open workspace"
        );
        assert_eq!(asked["languages"], json!(["python", "javascript"]));
        let id = asked["id"].as_str().expect("an id").to_owned();

        let coding = stub
            .interview("iv", InterviewAction::Coding, None)
            .expect("coding");
        let question = &coding["question"];
        assert_eq!(question["question_id"], id.as_str());
        assert_eq!(question["time_limit_seconds"], 600);
        assert!(
            question["starter_code"]["python"]
                .as_str()
                .is_some_and(|s| s.contains("def"))
        );
        assert!(
            question["asked_at"]
                .as_str()
                .is_some_and(|s| s.ends_with('Z'))
        );
        assert!(question["draft"].is_null());

        // A draft is kept and comes back after a restart.
        let draft = json!({ "question_id": id, "kind": "code", "language": "python",
                            "content": "print(1)" });
        stub.interview("iv", InterviewAction::Workspace, Some(&draft))
            .expect("saved");
        let coding = stub
            .interview("iv", InterviewAction::Coding, None)
            .expect("coding");
        assert_eq!(coding["question"]["draft"]["content"], "print(1)");
        assert_eq!(coding["question"]["draft"]["language"], "python");

        // Integrity events: kinds and lengths only.
        let events = json!({ "question_id": id, "events": [
            { "kind": "focus", "at": "2026-11-14T10:00:00Z" },
            { "kind": "paste", "at": "2026-11-14T10:00:01Z", "chars": 12 } ] });
        let accepted = stub
            .interview("iv", InterviewAction::CodingTelemetry, Some(&events))
            .expect("accepted");
        assert_eq!(accepted["accepted"], 2);
        let with_text = json!({ "question_id": id, "events": [
            { "kind": "paste", "at": "2026-11-14T10:00:01Z", "chars": 3, "text": "abc" } ] });
        assert_eq!(
            stub.interview("iv", InterviewAction::CodingTelemetry, Some(&with_text))
                .unwrap_err()
                .code,
            "unknown-event"
        );
        // As the server's schema: 1 to 200 events, else a validation error.
        let empty = json!({ "question_id": id, "events": [] });
        assert_eq!(
            stub.interview("iv", InterviewAction::CodingTelemetry, Some(&empty))
                .unwrap_err()
                .code,
            "validation-failed"
        );

        // A language the question doesn't offer is refused; then one submission moves on.
        let sql = json!({ "question_id": id, "language": "sql", "code": "select 1" });
        assert_eq!(
            stub.interview("iv", InterviewAction::CodingSubmit, Some(&sql))
                .unwrap_err()
                .code,
            "language-not-offered"
        );
        let code = json!({ "question_id": id, "language": "python", "code": "print(1)" });
        let submitted = stub
            .interview("iv", InterviewAction::CodingSubmit, Some(&code))
            .expect("submitted");
        assert_eq!(submitted["submission"]["source"], "submitted");
        assert_eq!(submitted["submission"]["size"], 8);
        assert_ne!(submitted["state"]["question"]["id"], id.as_str());
        assert_eq!(
            stub.interview("iv", InterviewAction::CodingSubmit, Some(&code))
                .unwrap_err()
                .code,
            "question-not-current"
        );
    }

    #[test]
    fn the_stub_phone_scans_the_code_then_connects() {
        let stub = Stub::default();
        assert_eq!(stub.third_eye_pair().unwrap_err().code, "signed-out");
        stub.sign_in("asha@x.test", PASSWORD).expect("signed in");
        let code = stub.third_eye_pair().expect("a code");
        assert_eq!(code.status, "issued");
        assert!(code.qr.is_some() && code.link.is_some());
        let seen: Vec<String> = (0..4)
            .map(|_| stub.third_eye_status().expect("status").status)
            .collect();
        assert_eq!(seen, ["issued", "redeemed", "connected", "connected"]);
        let connected = stub.third_eye_status().expect("status");
        assert_eq!(
            connected.device.as_deref(),
            Some("Android 15 Chrome (stub)")
        );
        // A new code starts over.
        stub.third_eye_pair().expect("a new code");
        assert_eq!(stub.third_eye_status().expect("status").status, "issued");
    }

    #[test]
    fn dates_are_iso_8601_in_utc() {
        assert_eq!(
            iso(UNIX_EPOCH + Duration::from_secs(1_760_000_000)),
            "2025-10-09T08:53:20Z"
        );
    }
}
