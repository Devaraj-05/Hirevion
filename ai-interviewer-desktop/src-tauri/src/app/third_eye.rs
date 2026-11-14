//! The third eye on the desktop (contract third-eye.md; ADR-0040; plan
//! `2026-10-23-b4-desktop-third-eye-and-snapshots.md`). Rust pairs the phone with the
//! interview-session token and its DPoP proof, draws the QR code, and remembers each
//! interview's pairing (its id only, never a token), so a restart doesn't pair again and
//! disconnect a phone that is already in place.

use std::collections::HashMap;
use std::fmt::Write as _;
use std::path::PathBuf;
use std::sync::Mutex;

use hv_api_client::{Method, SessionManager};
use qrcodegen::{QrCode, QrCodeEcc};
use serde::Serialize;
use serde_json::{Value, json};
use tauri::State;

use super::error::{CommandError, CommandResult};
use super::interview::{SessionTokens, check_interview_id, send_path};
use super::state::{AppState, Backend};

/// White space around the code, in modules (the QR standard's quiet zone).
const QUIET_ZONE: i32 = 4;
/// How often the interview's watcher reads the pairing (plan: every 5 s).
const WATCH_EVERY: std::time::Duration = std::time::Duration::from_secs(5);

/// The QR code as an SVG path in a `size`×`size` view box: one square per dark module.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct QrView {
    pub size: i32,
    pub path: String,
}

/// What the phone step shows.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PairingView {
    pub pairing_id: String,
    /// `issued`, `redeemed`, `connected`, `disconnected`, `revoked` or `expired`.
    pub status: String,
    /// Only for a code that was just issued: the code to scan, and its link to type.
    pub qr: Option<QrView>,
    pub link: Option<String>,
    pub expires_at: Option<String>,
    /// The phone, as the server saw it ("iOS 18 Safari").
    pub device: Option<String>,
}

/// Draws `text` as a QR code (medium error correction).
pub fn qr_view(text: &str) -> Result<QrView, String> {
    let code = QrCode::encode_text(text, QrCodeEcc::Medium).map_err(|error| error.to_string())?;
    let mut path = String::new();
    for y in 0..code.size() {
        for x in 0..code.size() {
            if code.get_module(x, y) {
                let _ = write!(path, "M{} {}h1v1h-1z", x + QUIET_ZONE, y + QUIET_ZONE);
            }
        }
    }
    Ok(QrView {
        size: code.size() + 2 * QUIET_ZONE,
        path,
    })
}

/// A code is needed again only when the old one can no longer bring a phone: it expired
/// unscanned, or it was revoked. A phone that disconnected (a lock) reconnects by itself.
pub fn needs_code(status: &str) -> bool {
    matches!(status, "expired" | "revoked")
}

/// The heartbeat's `third_eye` (proctoring.md) from the interview's mode and the pairing's
/// status (`None`: no pairing).
pub fn heartbeat_value(mode: &str, status: Option<&str>) -> &'static str {
    if mode == "off" {
        return "not_required";
    }
    match status {
        Some("redeemed") => "connecting",
        Some("connected") => "connected",
        Some("disconnected") => "disconnected",
        _ => "not_paired",
    }
}

/// The interview watcher's value after one read (`None`: no pairing); a failed read keeps the
/// last value.
pub fn watched(
    mode: &str,
    read: Option<CommandResult<String>>,
    last: &'static str,
) -> &'static str {
    match read {
        None => heartbeat_value(mode, None),
        Some(Ok(status)) => heartbeat_value(mode, Some(&status)),
        Some(Err(_)) => last,
    }
}

/// What the interview's third-eye watcher needs: the mode the briefing named, and the pairing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThirdEyeWatch {
    pub mode: String,
    pub pairing_id: Option<String>,
}

/// Reads the pairing every five seconds during the interview and keeps the heartbeat's value
/// current through `set`.
pub async fn watch_third_eye(
    session: std::sync::Arc<SessionManager>,
    tokens: std::sync::Arc<SessionTokens>,
    interview_id: String,
    watch: ThirdEyeWatch,
    set: impl Fn(&'static str) + Send + Sync,
) {
    let mut last = heartbeat_value(&watch.mode, None);
    loop {
        let read = match (&watch.pairing_id, watch.mode.as_str()) {
            (_, "off") | (None, _) => None,
            (Some(pairing_id), _) => Some(
                status(&session, &tokens, &interview_id, pairing_id)
                    .await
                    .map(|view| view.status),
            ),
        };
        last = watched(&watch.mode, read, last);
        set(last);
        tokio::time::sleep(WATCH_EVERY).await;
    }
}

/// What becomes of the remembered pairing, from its status read before a code is issued.
#[derive(Debug, Clone, PartialEq)]
pub enum Remembered {
    /// A phone is in place (or on its way): keep it.
    Keep(PairingView),
    /// The pairing is gone, spent, or an unscanned code whose token isn't kept: issue a new one.
    Replace,
    /// The read failed for another reason: say so, and never revoke a phone that may be in
    /// place by issuing a new code.
    Fail(CommandError),
}

pub fn remembered(read: CommandResult<PairingView>) -> Remembered {
    match read {
        Ok(view) if needs_code(&view.status) || view.status == "issued" => Remembered::Replace,
        Ok(view) => Remembered::Keep(view),
        Err(error) if matches!(error.code.as_str(), "pairing-not-found" | "not-found") => {
            Remembered::Replace
        }
        Err(error) => Remembered::Fail(error),
    }
}

/// Pairing ids are UUIDs; anything else never reaches a URL path.
fn check_pairing_id(pairing_id: &str) -> CommandResult<()> {
    let valid = !pairing_id.is_empty()
        && pairing_id.len() <= 64
        && pairing_id
            .chars()
            .all(|c| c.is_ascii_hexdigit() || c == '-');
    if valid {
        Ok(())
    } else {
        Err(CommandError::new(
            "unexpected-response",
            "bad pairing id".to_owned(),
        ))
    }
}

/// `GET /third-eye/pairings/{id}`'s answer as the phone step shows it.
pub fn status_view(pairing_id: &str, answer: &Value) -> PairingView {
    PairingView {
        pairing_id: pairing_id.to_owned(),
        status: answer["status"].as_str().unwrap_or("issued").to_owned(),
        qr: None,
        link: None,
        expires_at: answer["expires_at"].as_str().map(str::to_owned),
        device: answer["device"]["platform"].as_str().map(str::to_owned),
    }
}

/// `POST /third-eye/pairings`'s answer, with its QR code.
pub fn issued_view(answer: &Value) -> CommandResult<PairingView> {
    let bad = |what: &str| CommandError::new("unexpected-response", format!("pairing: {what}"));
    let pairing_id = answer["pairing_id"].as_str().ok_or_else(|| bad("no id"))?;
    check_pairing_id(pairing_id)?;
    let link = answer["qr_url"].as_str().ok_or_else(|| bad("no link"))?;
    let qr = qr_view(link).map_err(|error| bad(&error))?;
    Ok(PairingView {
        pairing_id: pairing_id.to_owned(),
        status: answer["status"].as_str().unwrap_or("issued").to_owned(),
        qr: Some(qr),
        link: Some(link.to_owned()),
        expires_at: answer["expires_at"].as_str().map(str::to_owned),
        device: None,
    })
}

/// Each interview's pairing id, kept in a small file in the app's data folder.
#[derive(Default)]
pub struct Pairings {
    file: Option<PathBuf>,
    ids: Mutex<HashMap<String, String>>,
    /// Each interview's third-eye mode, from the briefing the server last sent (not saved: the
    /// briefing is read again before every interview).
    modes: Mutex<HashMap<String, String>>,
}

impl Pairings {
    /// Reads `file` if it is there; a missing or unreadable file starts empty.
    pub fn load(file: PathBuf) -> Self {
        let ids = std::fs::read(&file)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<HashMap<String, String>>(&bytes).ok())
            .unwrap_or_default();
        Self {
            file: Some(file),
            ids: Mutex::new(ids),
            modes: Mutex::new(HashMap::new()),
        }
    }

    /// Notes the briefing's `third_eye` (the server's word, with a waiver already applied).
    pub fn note_briefing(&self, interview_id: &str, briefing: &Value) {
        let Some(mode) = briefing["third_eye"].as_str() else {
            return;
        };
        if matches!(mode, "off" | "optional" | "required")
            && let Ok(mut modes) = self.modes.lock()
        {
            modes.insert(interview_id.to_owned(), mode.to_owned());
        }
    }

    /// The interview's third-eye mode; `off` until a briefing named it.
    pub fn mode(&self, interview_id: &str) -> String {
        self.modes
            .lock()
            .ok()
            .and_then(|modes| modes.get(interview_id).cloned())
            .unwrap_or_else(|| "off".to_owned())
    }

    /// What the interview's watcher needs.
    pub fn watch(&self, interview_id: &str) -> ThirdEyeWatch {
        ThirdEyeWatch {
            mode: self.mode(interview_id),
            pairing_id: self.get(interview_id),
        }
    }

    pub fn get(&self, interview_id: &str) -> Option<String> {
        self.ids.lock().ok()?.get(interview_id).cloned()
    }

    pub fn put(&self, interview_id: &str, pairing_id: &str) {
        if let Ok(mut ids) = self.ids.lock() {
            ids.insert(interview_id.to_owned(), pairing_id.to_owned());
            self.save(&ids);
        }
    }

    fn save(&self, ids: &HashMap<String, String>) {
        let Some(file) = &self.file else { return };
        if let Ok(bytes) = serde_json::to_vec(ids)
            && let Err(error) = std::fs::write(file, bytes)
        {
            eprintln!("third eye: the pairing couldn't be saved: {error}");
        }
    }
}

async fn issue(
    session: &SessionManager,
    tokens: &SessionTokens,
    pairings: &Pairings,
    interview_id: &str,
) -> CommandResult<PairingView> {
    let body = json!({ "interview_id": interview_id });
    let answer = send_path(
        session,
        tokens,
        interview_id,
        Method::POST,
        "third-eye/pairings",
        Some(&body),
    )
    .await?;
    let view = issued_view(&answer)?;
    pairings.put(interview_id, &view.pairing_id);
    Ok(view)
}

async fn status(
    session: &SessionManager,
    tokens: &SessionTokens,
    interview_id: &str,
    pairing_id: &str,
) -> CommandResult<PairingView> {
    check_pairing_id(pairing_id)?;
    let path = format!("third-eye/pairings/{pairing_id}");
    let answer = send_path(session, tokens, interview_id, Method::GET, &path, None).await?;
    Ok(status_view(pairing_id, &answer))
}

/// The phone step's code. Without `replace`, a pairing that already brought a phone (or is
/// bringing one) is kept; otherwise, or when its code expired or was revoked, a new code is
/// issued (the server revokes the old one and disconnects its phone).
#[tauri::command]
pub async fn third_eye_pair(
    state: State<'_, AppState>,
    interview_id: String,
    replace: bool,
) -> CommandResult<PairingView> {
    check_interview_id(&interview_id)?;
    let session = match &state.backend {
        Backend::Stub(stub) => return stub.third_eye_pair(),
        Backend::Live(session) => session,
    };
    let tokens = &state.session_tokens;
    if !replace && let Some(pairing_id) = state.third_eye.get(&interview_id) {
        // A restart, or back to this step: keep a phone that is in place.
        match remembered(status(session, tokens, &interview_id, &pairing_id).await) {
            Remembered::Keep(view) => return Ok(view),
            Remembered::Fail(error) => return Err(error),
            Remembered::Replace => {}
        }
    }
    issue(session, tokens, &state.third_eye, &interview_id).await
}

/// The third eye's heartbeat value during the interview (`None` when nothing watches it);
/// the interview screen's status bar shows it.
#[tauri::command]
pub async fn third_eye_live(state: State<'_, AppState>) -> CommandResult<Option<String>> {
    if let Backend::Stub(stub) = &state.backend {
        return Ok(Some(stub.third_eye_live().to_owned()));
    }
    Ok(state.services.third_eye_value().map(str::to_owned))
}

/// The pairing's status, read every two seconds while the phone step is open.
#[tauri::command]
pub async fn third_eye_status(
    state: State<'_, AppState>,
    interview_id: String,
) -> CommandResult<PairingView> {
    check_interview_id(&interview_id)?;
    let session = match &state.backend {
        Backend::Stub(stub) => return stub.third_eye_status(),
        Backend::Live(session) => session,
    };
    let Some(pairing_id) = state.third_eye.get(&interview_id) else {
        return Err(CommandError::new("not-paired", None));
    };
    status(session, &state.session_tokens, &interview_id, &pairing_id).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn draws_the_link_as_a_qr_code_with_its_quiet_zone() {
        let link = "https://eye.hirevion.localhost/#t=0123456789abcdef0123456789abcdef";
        let qr = qr_view(link).expect("a code");
        let code = QrCode::encode_text(link, QrCodeEcc::Medium).expect("a code");
        assert_eq!(qr.size, code.size() + 8);
        // One square per dark module, none in the quiet zone.
        let squares = qr.path.matches('M').count();
        let dark = (0..code.size())
            .flat_map(|y| (0..code.size()).map(move |x| (x, y)))
            .filter(|&(x, y)| code.get_module(x, y))
            .count();
        assert_eq!(squares, dark);
        assert!(
            qr.path.starts_with("M4 4h1v1h-1z"),
            "the finder pattern's corner"
        );
        assert_eq!(qr_view(link), Ok(qr));
    }

    #[test]
    fn keeps_a_phone_in_place_unless_the_pairing_is_gone_or_spent() {
        let view = |status: &str| status_view("p1", &json!({ "status": status }));
        for status in ["redeemed", "connected", "disconnected"] {
            assert_eq!(
                remembered(Ok(view(status))),
                Remembered::Keep(view(status)),
                "{status}"
            );
        }
        for status in ["issued", "expired", "revoked"] {
            assert_eq!(
                remembered(Ok(view(status))),
                Remembered::Replace,
                "{status}"
            );
        }
        let gone = CommandError::new("pairing-not-found", None);
        assert_eq!(remembered(Err(gone)), Remembered::Replace);
        // A blip must not revoke a connected phone by issuing a new code.
        let blip = CommandError::new("network", None);
        assert_eq!(remembered(Err(blip.clone())), Remembered::Fail(blip));
    }

    #[test]
    fn a_new_code_is_needed_only_when_the_old_one_is_spent() {
        for status in ["expired", "revoked"] {
            assert!(needs_code(status), "{status}");
        }
        for status in ["issued", "redeemed", "connected", "disconnected"] {
            assert!(!needs_code(status), "{status}");
        }
    }

    #[test]
    fn reads_the_servers_answers() {
        let issued = issued_view(&json!({
            "pairing_id": "0190f1a2-0000-7000-8000-00000000000a",
            "qr_url": "https://eye.hirevion.localhost/#t=abc",
            "expires_at": "2026-11-15T05:00:00Z",
            "status": "issued"
        }))
        .expect("issued");
        assert_eq!(
            issued.link.as_deref(),
            Some("https://eye.hirevion.localhost/#t=abc")
        );
        assert!(issued.qr.is_some());
        let refused = issued_view(&json!({ "pairing_id": "../x", "qr_url": "https://e/#t=a" }));
        assert_eq!(refused.unwrap_err().code, "unexpected-response");

        let seen = status_view(
            "p1",
            &json!({ "status": "connected", "device": { "platform": "iOS 18 Safari" } }),
        );
        assert_eq!(
            (seen.status.as_str(), seen.device.as_deref()),
            ("connected", Some("iOS 18 Safari"))
        );
        assert!(seen.qr.is_none() && seen.link.is_none());
        let fresh = status_view("p1", &json!({ "status": "issued", "device": null }));
        assert_eq!(fresh.device, None);
    }

    #[test]
    fn the_heartbeat_reports_the_phone_as_the_contract_names_it() {
        assert_eq!(heartbeat_value("off", Some("connected")), "not_required");
        assert_eq!(heartbeat_value("required", None), "not_paired");
        for status in ["issued", "expired", "revoked"] {
            assert_eq!(
                heartbeat_value("optional", Some(status)),
                "not_paired",
                "{status}"
            );
        }
        assert_eq!(heartbeat_value("required", Some("redeemed")), "connecting");
        assert_eq!(heartbeat_value("required", Some("connected")), "connected");
        assert_eq!(
            heartbeat_value("optional", Some("disconnected")),
            "disconnected"
        );
    }

    #[test]
    fn a_failed_read_keeps_the_last_value() {
        let failed = Err(CommandError::new("network", None));
        assert_eq!(watched("required", Some(failed), "connected"), "connected");
        assert_eq!(
            watched("required", Some(Ok("disconnected".into())), "connected"),
            "disconnected"
        );
        // No pairing at all.
        assert_eq!(watched("required", None, "connected"), "not_paired");
    }

    #[test]
    fn remembers_each_interviews_mode_from_its_briefing() {
        let pairings = Pairings::default();
        assert_eq!(pairings.mode("iv"), "off");
        pairings.note_briefing("iv", &json!({ "third_eye": "required" }));
        assert_eq!(pairings.mode("iv"), "required");
        // Anything the contract doesn't name is ignored.
        pairings.note_briefing("iv", &json!({ "third_eye": "sometimes" }));
        assert_eq!(pairings.mode("iv"), "required");
    }

    #[test]
    fn remembers_pairings_across_a_restart() {
        let folder = std::env::temp_dir().join(format!("hv-third-eye-{}", std::process::id()));
        std::fs::create_dir_all(&folder).expect("folder");
        let file = folder.join("third-eye.json");
        let _ = std::fs::remove_file(&file);

        let pairings = Pairings::load(file.clone());
        assert_eq!(pairings.get("iv"), None);
        pairings.put("iv", "p1");
        pairings.put("iv", "p2");
        let again = Pairings::load(file.clone());
        assert_eq!(again.get("iv").as_deref(), Some("p2"));
        // Only ids are written, never a token.
        let text = std::fs::read_to_string(&file).expect("saved");
        assert_eq!(text, r#"{"iv":"p2"}"#);

        std::fs::write(&file, b"not json").expect("garbage");
        assert_eq!(Pairings::load(file.clone()).get("iv"), None);
        let _ = std::fs::remove_dir_all(&folder);
    }
}
