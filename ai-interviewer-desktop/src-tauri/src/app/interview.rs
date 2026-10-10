//! The interview calls (contract interview-session), made from Rust with the interview's
//! session token. The webview names an action from a fixed list; it never builds a path or
//! holds the token (ADR-0018). The one thing it does receive is the LiveKit participant token
//! from `start`: a short-lived media token the in-webview LiveKit client needs to join the room.

use std::collections::HashMap;
use std::sync::Mutex;

use hv_api_client::{ApiError, Method, SessionManager};
use serde::Deserialize;
use tauri::State;

use super::error::{CommandError, CommandResult};
use super::state::{AppState, Backend};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InterviewAction {
    Briefing,
    SystemChecks,
    Consents,
    Accommodations,
    Start,
    Session,
    Answer,
    Workspace,
    Complete,
}

impl InterviewAction {
    pub fn route(self) -> (Method, &'static str) {
        match self {
            Self::Briefing => (Method::GET, "briefing"),
            Self::SystemChecks => (Method::POST, "system-checks"),
            Self::Consents => (Method::POST, "consents"),
            Self::Accommodations => (Method::POST, "accommodations"),
            Self::Start => (Method::POST, "start"),
            Self::Session => (Method::GET, "session"),
            Self::Answer => (Method::POST, "answer"),
            Self::Workspace => (Method::POST, "workspace"),
            Self::Complete => (Method::POST, "complete"),
        }
    }
}

/// Interview ids are UUIDs; anything else never reaches a URL path, a file name or a store.
pub fn check_interview_id(interview_id: &str) -> CommandResult<()> {
    let valid = !interview_id.is_empty()
        && interview_id.len() <= 64
        && interview_id
            .chars()
            .all(|c| c.is_ascii_hexdigit() || c == '-');
    if valid {
        Ok(())
    } else {
        Err(CommandError::new("invalid-interview", None))
    }
}

pub fn interview_path(interview_id: &str, rest: &str) -> CommandResult<String> {
    check_interview_id(interview_id)?;
    Ok(format!("interviews/{interview_id}/{rest}"))
}

/// Session tokens per interview, kept until the server rejects one.
#[derive(Default)]
pub struct SessionTokens(Mutex<HashMap<String, String>>);

impl SessionTokens {
    pub fn get(&self, interview_id: &str) -> Option<String> {
        self.0.lock().ok()?.get(interview_id).cloned()
    }

    pub fn put(&self, interview_id: &str, token: String) {
        if let Ok(mut tokens) = self.0.lock() {
            tokens.insert(interview_id.to_owned(), token);
        }
    }

    pub fn forget(&self, interview_id: &str) {
        if let Ok(mut tokens) = self.0.lock() {
            tokens.remove(interview_id);
        }
    }
}

pub async fn session_token(
    session: &SessionManager,
    tokens: &SessionTokens,
    interview_id: &str,
) -> Result<String, ApiError> {
    if let Some(token) = tokens.get(interview_id) {
        return Ok(token);
    }
    let token = session.session_token(interview_id).await?.session_token;
    tokens.put(interview_id, token.clone());
    Ok(token)
}

/// Sends one interview call; a rejected session token (`token-invalid`, e.g. expired) is
/// replaced once.
pub async fn send(
    session: &SessionManager,
    tokens: &SessionTokens,
    interview_id: &str,
    action: InterviewAction,
    body: Option<&serde_json::Value>,
) -> CommandResult<serde_json::Value> {
    let (method, rest) = action.route();
    let path = interview_path(interview_id, rest)?;
    for attempt in 0..2 {
        let token = session_token(session, tokens, interview_id).await?;
        let answer = session
            .api()
            .send_value(method.clone(), &path, body, Some(&token))
            .await;
        match answer {
            Err(error) if attempt == 0 && error.is_problem("token-invalid") => {
                tokens.forget(interview_id);
            }
            other => return other.map_err(CommandError::from),
        }
    }
    Err(CommandError::new("signed-out", None))
}

#[tauri::command]
pub async fn interview_request(
    state: State<'_, AppState>,
    interview_id: String,
    action: InterviewAction,
    body: Option<serde_json::Value>,
) -> CommandResult<serde_json::Value> {
    match &state.backend {
        Backend::Stub(stub) => stub.interview(&interview_id, action, body.as_ref()),
        Backend::Live(session) => {
            send(
                session,
                &state.session_tokens,
                &interview_id,
                action,
                body.as_ref(),
            )
            .await
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_uuid_like_interview_ids_reach_a_path() {
        assert_eq!(
            interview_path("0190f1a2-0000-7000-8000-000000000000", "start").expect("valid"),
            "interviews/0190f1a2-0000-7000-8000-000000000000/start"
        );
        for bad in ["", "../me", "a/b", "x?y=1", "%2e%2e"] {
            assert_eq!(
                interview_path(bad, "start").unwrap_err().code,
                "invalid-interview"
            );
        }
    }

    #[test]
    fn every_action_maps_to_the_contract() {
        let action: InterviewAction = serde_json::from_str("\"system_checks\"").expect("known");
        assert_eq!(action.route(), (Method::POST, "system-checks"));
        assert_eq!(InterviewAction::Briefing.route(), (Method::GET, "briefing"));
        assert_eq!(InterviewAction::Session.route(), (Method::GET, "session"));
        assert!(serde_json::from_str::<InterviewAction>("\"logout\"").is_err());
    }

    #[test]
    fn a_forgotten_token_is_fetched_again() {
        let tokens = SessionTokens::default();
        tokens.put("iv", "t1".into());
        assert_eq!(tokens.get("iv").as_deref(), Some("t1"));
        tokens.forget("iv");
        assert_eq!(tokens.get("iv"), None);
    }
}
