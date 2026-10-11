//! Crash reporting to GlitchTip (Sentry-compatible), SP-08c, ADR-0019.
//!
//! Off unless `HV_GLITCHTIP_DSN` was set when the app was built. When on, Rust panics are
//! reported by the `sentry` panic integration and webview errors arrive through the
//! `crash_report` command, so the webview never contacts GlitchTip itself (its CSP stays shut).
//!
//! Nothing identifying leaves the machine: every event passes [`scrub_event`] first, which
//! drops the user, the request, the computer's name and any source line or variable, and
//! redacts emails, tokens, user-profile paths and addresses from every string.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, LazyLock};

use regex::Regex;
use sentry::protocol::{Context, Event, Exception, Frame, Level, Stacktrace, Value};
use sentry::{ClientInitGuard, ClientOptions};
use serde::Deserialize;

/// The GlitchTip project's DSN, fixed at build time. Absent means crash reporting is off.
const DSN: Option<&str> = option_env!("HV_GLITCHTIP_DSN");
/// A runaway render loop must not flood the project: this many webview reports per run.
const MAX_WEBVIEW_REPORTS: u32 = 25;
const MAX_MESSAGE: usize = 2_000;
const MAX_STACK: usize = 6_000;

static WEBVIEW_REPORTS: AtomicU32 = AtomicU32::new(0);

// Each pattern is checked by `redacts_*` tests below; the order matters (specific first).
static PATTERNS: LazyLock<Vec<(Regex, &'static str)>> = LazyLock::new(|| {
    let rules: [(&str, &str); 8] = [
        // JSON web tokens (access and interview-session tokens, DPoP proofs).
        (
            r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*",
            "[token]",
        ),
        // Our refresh tokens.
        (r"\brt_[A-Za-z0-9_\-]{8,}", "[token]"),
        // "Authorization: DPoP abc…", "Bearer abc…".
        (
            r"(?i)\b(bearer|dpop|basic)\s+[A-Za-z0-9._~+/=\-]{8,}",
            "$1 [token]",
        ),
        // token=…, "password": "…", otp: …
        (
            r#"(?i)\b(access_token|refresh_token|id_token|token|password|passwd|secret|api[_-]?key|authorization|cookie|otp)\b(["']?\s*[:=]\s*["']?)[^\s"',;&})\]]+"#,
            "$1$2[redacted]",
        ),
        (
            r"(?i)[a-z0-9._%+\-]+@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+",
            "[email]",
        ),
        // C:\Users\<name>\…, /Users/<name>/…, /home/<name>/…
        (
            r"(?i)([a-z]:[\\/]+users[\\/]+|/users/|/home/)[^\\/\s:*?<>|]+",
            "${1}[user]",
        ),
        (r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "[ip]"),
        // Any other long opaque run (keys, hashes, ids with no separators).
        (r"\b[A-Za-z0-9_\-]{40,}\b", "[redacted]"),
    ];
    rules
        .into_iter()
        .map(|(pattern, replacement)| (Regex::new(pattern).expect("a valid pattern"), replacement))
        .collect()
});

/// `text` with emails, tokens, profile paths, addresses and other opaque strings redacted.
pub fn scrub_text(text: &str) -> String {
    PATTERNS
        .iter()
        .fold(text.to_owned(), |text, (pattern, replacement)| {
            pattern.replace_all(&text, *replacement).into_owned()
        })
}

fn sensitive_key(key: &str) -> bool {
    let key = key.to_ascii_lowercase();
    key == "ip"
        || key.ends_with("_ip")
        || [
            "email",
            "name",
            "token",
            "password",
            "secret",
            "authorization",
            "cookie",
            "phone",
            "otp",
            "address",
        ]
        .iter()
        .any(|word| key.contains(word))
}

fn scrub_value(value: &mut Value) {
    match value {
        Value::String(text) => *text = scrub_text(text),
        Value::Array(items) => items.iter_mut().for_each(scrub_value),
        Value::Object(fields) => {
            for (key, field) in fields.iter_mut() {
                if sensitive_key(key) {
                    *field = Value::String("[redacted]".into());
                } else {
                    scrub_value(field);
                }
            }
        }
        _ => {}
    }
}

fn scrub_map(map: &mut BTreeMap<String, Value>) {
    for (key, value) in map.iter_mut() {
        if sensitive_key(key) {
            *value = Value::String("[redacted]".into());
        } else {
            scrub_value(value);
        }
    }
}

fn scrub_frame(frame: &mut Frame) {
    frame.abs_path = frame.abs_path.as_deref().map(scrub_text);
    frame.filename = frame.filename.as_deref().map(scrub_text);
    // Source lines and local variables can hold anything the candidate typed.
    frame.pre_context.clear();
    frame.context_line = None;
    frame.post_context.clear();
    frame.vars.clear();
}

fn scrub_stacktrace(stacktrace: &mut Stacktrace) {
    stacktrace.frames.iter_mut().for_each(scrub_frame);
}

fn scrub_exception(exception: &mut Exception) {
    exception.value = exception.value.as_deref().map(scrub_text);
    for stacktrace in [&mut exception.stacktrace, &mut exception.raw_stacktrace]
        .into_iter()
        .flatten()
    {
        scrub_stacktrace(stacktrace);
    }
}

/// Removes everything that could identify the candidate or their computer from an event.
pub fn scrub_event(mut event: Event<'static>) -> Event<'static> {
    event.user = None;
    event.request = None;
    event.server_name = None;
    event.transaction = None;
    event.template = None;
    event.culprit = event.culprit.as_deref().map(scrub_text);
    event.message = event.message.as_deref().map(scrub_text);
    if let Some(entry) = &mut event.logentry {
        entry.message = scrub_text(&entry.message);
        entry.params.iter_mut().for_each(scrub_value);
    }
    event.exception.values.iter_mut().for_each(scrub_exception);
    if let Some(stacktrace) = &mut event.stacktrace {
        scrub_stacktrace(stacktrace);
    }
    for thread in &mut event.threads.values {
        thread.name = None;
        for stacktrace in [&mut thread.stacktrace, &mut thread.raw_stacktrace]
            .into_iter()
            .flatten()
        {
            scrub_stacktrace(stacktrace);
        }
    }
    for breadcrumb in &mut event.breadcrumbs.values {
        breadcrumb.message = breadcrumb.message.as_deref().map(scrub_text);
        scrub_map(&mut breadcrumb.data);
    }
    for context in event.contexts.values_mut() {
        if let Context::Device(device) = context {
            device.name = None;
        }
    }
    for value in event.tags.values_mut() {
        *value = scrub_text(value);
    }
    event.tags.retain(|key, _| !sensitive_key(key));
    scrub_map(&mut event.extra);
    event
}

/// What the webview reports about one of its errors.
#[derive(Debug, Clone, Deserialize)]
pub struct WebviewError {
    /// `error`, `unhandledrejection` or `render`.
    pub kind: String,
    pub message: String,
    pub stack: Option<String>,
}

fn truncate(text: &str, max: usize) -> String {
    text.chars().take(max).collect()
}

/// The event for a webview error, before scrubbing.
fn webview_event(error: &WebviewError) -> Event<'static> {
    let mut event = Event {
        level: Level::Error,
        logger: Some("webview".into()),
        message: Some(format!(
            "{}: {}",
            truncate(&error.kind, 40),
            truncate(&error.message, MAX_MESSAGE)
        )),
        ..Event::default()
    };
    event.tags.insert("origin".into(), "webview".into());
    if let Some(stack) = &error.stack {
        event
            .extra
            .insert("stack".into(), Value::String(truncate(stack, MAX_STACK)));
    }
    event
}

/// Reports a webview error, scrubbed, when crash reporting is on (and within the cap).
pub fn capture_webview_error(error: &WebviewError) {
    // A client built from an empty DSN is bound to the hub but disabled.
    if !sentry::Hub::current()
        .client()
        .is_some_and(|client| client.is_enabled())
    {
        return;
    }
    if WEBVIEW_REPORTS.fetch_add(1, Ordering::Relaxed) >= MAX_WEBVIEW_REPORTS {
        return;
    }
    // `before_send` scrubs again; doing it here too keeps the pure function the one under test.
    sentry::capture_event(scrub_event(webview_event(error)));
}

#[tauri::command]
pub fn crash_report(error: WebviewError) {
    capture_webview_error(&error);
}

fn options(version: &str) -> ClientOptions {
    // ClientOptions is non-exhaustive, so it is filled in field by field.
    let mut options = ClientOptions::default();
    options.release = Some(format!("hirevion-desktop@{version}").into());
    options.environment = Some(
        if cfg!(debug_assertions) {
            "development"
        } else {
            "production"
        }
        .into(),
    );
    options.send_default_pii = false;
    options.attach_stacktrace = true;
    options.server_name = None;
    options.max_breadcrumbs = 20;
    options.auto_session_tracking = false;
    options.before_send = Some(Arc::new(|event| Some(scrub_event(event))));
    options.before_breadcrumb = Some(Arc::new(|mut breadcrumb| {
        breadcrumb.message = breadcrumb.message.as_deref().map(scrub_text);
        scrub_map(&mut breadcrumb.data);
        Some(breadcrumb)
    }));
    options
}

/// Starts crash reporting when this build has a DSN; keep the guard alive for the whole run.
pub fn init(version: &str) -> Option<ClientInitGuard> {
    init_with(DSN?, version)
}

fn init_with(dsn: &str, version: &str) -> Option<ClientInitGuard> {
    let guard = sentry::init((dsn, options(version)));
    guard.is_enabled().then_some(guard)
}

/// Sends what is queued before the process ends.
pub fn flush() {
    if let Some(client) = sentry::Hub::current().client() {
        client.flush(Some(std::time::Duration::from_secs(2)));
    }
}

#[cfg(test)]
mod tests {
    use sentry::protocol::{Breadcrumb, DeviceContext, LogEntry, Request, Thread, User};

    use super::*;

    const EMAIL: &str = "asha.rao@example.test";
    // A made-up token ({"alg":"ES256"}.{"sub":"asha"}."signature-bytes"), built from its parts
    // so secret scanners don't take the test data for a real credential.
    const JWT: &str = concat!(
        "eyJhbGciOiJFUzI1NiJ9",
        ".",
        "eyJzdWIiOiJhc2hhIn0",
        ".",
        "c2lnbmF0dXJlLWJ5dGVz"
    );

    #[test]
    fn redacts_emails_tokens_paths_and_addresses() {
        let text = format!(
            "failed for {EMAIL}: Authorization: DPoP {JWT}; refresh rt_abcdef0123456789xyz; \
             \"password\": \"hunter2hunter2\"; at C:\\Users\\asha\\AppData\\Local\\app.dll; \
             from 203.0.113.7; key {}",
            "A".repeat(48)
        );
        let clean = scrub_text(&text);
        for secret in [
            EMAIL,
            "eyJhbGci",
            "rt_abcdef",
            "hunter2",
            "asha\\",
            "203.0.113.7",
            &"A".repeat(40),
        ] {
            assert!(!clean.contains(secret), "{secret:?} survived in {clean}");
        }
        assert!(clean.contains("C:\\Users\\[user]\\AppData"), "{clean}");
        assert!(clean.contains("failed for [email]"), "{clean}");
    }

    #[test]
    fn keeps_ordinary_diagnostics() {
        let text =
            "index out of bounds at src/app/update.rs:42 (version 0.1.0, Windows 11 26200.9457)";
        assert_eq!(scrub_text(text), text);
    }

    #[test]
    fn scrubbing_twice_changes_nothing() {
        let once = scrub_text(&format!("{EMAIL} {JWT}"));
        assert_eq!(scrub_text(&once), once);
    }

    #[test]
    fn strips_identity_from_a_whole_event() {
        let mut event = Event {
            message: Some(format!("could not sign in {EMAIL}")),
            server_name: Some("ASHA-LAPTOP".into()),
            user: Some(User {
                email: Some(EMAIL.into()),
                username: Some("Asha Rao".into()),
                ip_address: Some(sentry::protocol::IpAddress::Auto),
                ..User::default()
            }),
            request: Some(Request {
                url: Some(
                    "https://api.example.test/?token=abc"
                        .parse()
                        .expect("a URL"),
                ),
                ..Request::default()
            }),
            logentry: Some(LogEntry {
                message: format!("hello {EMAIL}"),
                params: vec![Value::String(JWT.into())],
            }),
            ..Event::default()
        };
        event.exception.values.push(Exception {
            ty: "panic".into(),
            value: Some(format!("{EMAIL} at C:\\Users\\asha\\x")),
            stacktrace: Some(Stacktrace {
                frames: vec![Frame {
                    abs_path: Some("C:\\Users\\asha\\repo\\lib.rs".into()),
                    context_line: Some(format!("let email = \"{EMAIL}\";")),
                    vars: [("name".to_owned(), Value::String("Asha Rao".into()))].into(),
                    ..Frame::default()
                }],
                ..Stacktrace::default()
            }),
            ..Exception::default()
        });
        event.threads.values.push(Thread {
            name: Some("Asha's thread".into()),
            ..Thread::default()
        });
        event.breadcrumbs.values.push(Breadcrumb {
            message: Some(format!("opened {EMAIL}")),
            data: [
                ("email".to_owned(), Value::String(EMAIL.into())),
                ("step".to_owned(), Value::String("briefing".into())),
            ]
            .into(),
            ..Breadcrumb::default()
        });
        event.contexts.insert(
            "device".into(),
            DeviceContext {
                name: Some("ASHA-LAPTOP".into()),
                arch: Some("x86_64".into()),
                ..DeviceContext::default()
            }
            .into(),
        );
        event.tags.insert("candidate_email".into(), EMAIL.into());
        event.tags.insert("arch".into(), "x64".into());
        event
            .extra
            .insert("name".into(), Value::String("Asha Rao".into()));
        event
            .extra
            .insert("note".into(), Value::String(format!("{EMAIL} {JWT}")));

        let clean = scrub_event(event);
        let json = serde_json::to_string(&clean).expect("json");
        for secret in [
            EMAIL,
            "ASHA-LAPTOP",
            "Asha",
            "asha",
            "eyJhbGci",
            "token=abc",
        ] {
            assert!(!json.contains(secret), "{secret:?} survived in {json}");
        }
        assert!(clean.user.is_none() && clean.request.is_none() && clean.server_name.is_none());
        assert_eq!(clean.exception.values.len(), 1);
        // Diagnostics stay.
        assert!(json.contains("briefing") && json.contains("x86_64") && json.contains("\"arch\""));
    }

    #[test]
    fn a_webview_error_is_scrubbed_and_bounded() {
        let error = WebviewError {
            kind: "error".into(),
            message: format!("Cannot read {EMAIL} {}", "x".repeat(5_000)),
            stack: Some(format!("at {JWT}\n{}", "y ".repeat(10_000))),
        };
        let event = scrub_event(webview_event(&error));
        let json = serde_json::to_string(&event).expect("json");
        assert!(!json.contains(EMAIL) && !json.contains("eyJhbGci"));
        assert!(event.message.as_deref().is_some_and(|m| m.len() < 2_100));
        assert_eq!(
            event.tags.get("origin").map(String::as_str),
            Some("webview")
        );
        let stack = event
            .extra
            .get("stack")
            .and_then(Value::as_str)
            .expect("a stack");
        assert!(stack.chars().count() <= MAX_STACK);
    }

    #[test]
    fn the_client_is_configured_to_scrub_and_to_send_no_pii() {
        let options = options("1.2.3");
        assert!(!options.send_default_pii);
        assert!(options.before_send.is_some() && options.before_breadcrumb.is_some());
        assert_eq!(options.release.as_deref(), Some("hirevion-desktop@1.2.3"));
        let scrubbed = options.before_send.as_ref().expect("a hook")(Event {
            server_name: Some("ASHA-LAPTOP".into()),
            ..Event::default()
        })
        .expect("an event");
        assert!(scrubbed.server_name.is_none());
    }

    #[test]
    fn is_off_without_a_dsn_and_reports_nothing() {
        assert!(init_with("", "0.0.0").is_none());
        // No client is bound in tests, so a report is dropped before it counts.
        capture_webview_error(&WebviewError {
            kind: "error".into(),
            message: "x".into(),
            stack: None,
        });
        assert_eq!(WEBVIEW_REPORTS.load(Ordering::Relaxed), 0);
    }
}
