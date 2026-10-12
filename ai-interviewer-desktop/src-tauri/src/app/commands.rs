//! The commands the webview calls instead of the API (master plan §6.4, ADR-0018). Each
//! returns only what the screens show; tokens stay in Rust. Failures are `CommandError`s.

use hv_api_client::auth::{self, AppInfo, DeviceInfo, LoginRequest, OtpVerify};
use hv_system_check::CheckResult;
use tauri::State;

use super::error::{CommandError, CommandResult};
use super::state::{AppState, Backend};
use super::views::{AppInfoView, ProfileView, ReleaseView, RoundTripView, SignInView};

#[tauri::command]
pub fn app_info(state: State<'_, AppState>) -> AppInfoView {
    state.info.clone()
}

#[tauri::command]
pub async fn release_check(state: State<'_, AppState>) -> CommandResult<ReleaseView> {
    match &state.backend {
        Backend::Stub(_) => Ok(ReleaseView {
            status: "ok",
            latest_version: Some(state.info.version.clone()),
            minimum_version: None,
            download_url: None,
        }),
        Backend::Live(session) => {
            // Proofs carry server time; sync it before anything is signed.
            session.api().sync_clock().await?;
            let check = auth::release_check(
                session.api(),
                &state.info.version,
                &state.info.channel,
                &state.info.arch,
            )
            .await?;
            Ok(check.into())
        }
    }
}

#[tauri::command]
pub async fn sign_in(
    state: State<'_, AppState>,
    email: String,
    password: String,
) -> CommandResult<SignInView> {
    match &state.backend {
        Backend::Stub(stub) => stub.sign_in(email.trim(), &password),
        Backend::Live(session) => {
            let request = LoginRequest {
                email: email.trim().to_owned(),
                password,
                app: AppInfo {
                    version: state.info.version.clone(),
                    channel: state.info.channel.clone(),
                    os: state.info.os.clone(),
                    arch: state.info.arch.clone(),
                },
                device: DeviceInfo {
                    name: state.device_name.clone(),
                },
            };
            Ok(session.sign_in(&request).await?.into())
        }
    }
}

#[tauri::command]
pub async fn verify_code(
    state: State<'_, AppState>,
    challenge_id: String,
    code: String,
) -> CommandResult<SignInView> {
    match &state.backend {
        Backend::Stub(stub) => stub.verify_code(&challenge_id, &code),
        Backend::Live(session) => Ok(session
            .verify_code(&OtpVerify { challenge_id, code })
            .await?
            .into()),
    }
}

#[tauri::command]
pub async fn resend_code(state: State<'_, AppState>, challenge_id: String) -> CommandResult<()> {
    match &state.backend {
        Backend::Stub(_) => Ok(()),
        Backend::Live(session) => Ok(session.resend_code(&challenge_id).await?),
    }
}

/// Always ends the local session; a failed server-side logout isn't the candidate's problem.
#[tauri::command]
pub async fn sign_out(state: State<'_, AppState>) -> CommandResult<()> {
    match &state.backend {
        Backend::Stub(stub) => stub.sign_out(),
        Backend::Live(session) => {
            // The uploads need the session; the segments wait on disk for the next sign-in.
            state.services.cancel_background();
            let _ = session.sign_out().await;
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn profile(state: State<'_, AppState>) -> CommandResult<ProfileView> {
    match &state.backend {
        Backend::Stub(stub) => stub.profile(),
        Backend::Live(session) => {
            let me = session.me().await?;
            // Signed in: upload what an earlier run (a crash, a closed laptop) left behind.
            state.services.resume_pending();
            Ok(me.into())
        }
    }
}

#[tauri::command]
pub async fn native_checks(state: State<'_, AppState>) -> CommandResult<Vec<CheckResult>> {
    if let Backend::Stub(stub) = &state.backend
        && let Some(canned) = stub.native_checks()
    {
        return Ok(canned);
    }
    tauri::async_runtime::spawn_blocking(hv_system_check::native_checks)
        .await
        .map_err(|error| CommandError::new("check-failed", error.to_string()))
}

#[tauri::command]
pub async fn screen_capture_probe(state: State<'_, AppState>) -> CommandResult<CheckResult> {
    if let Backend::Stub(stub) = &state.backend
        && let Some(canned) = stub.screen_capture()
    {
        return Ok(canned);
    }
    tauri::async_runtime::spawn_blocking(hv_system_check::screen_capture_probe)
        .await
        .map_err(|error| CommandError::new("check-failed", error.to_string()))
}

#[tauri::command]
pub async fn api_round_trip(state: State<'_, AppState>) -> CommandResult<RoundTripView> {
    match &state.backend {
        Backend::Stub(_) => Ok(RoundTripView { rtt_ms: 42 }),
        Backend::Live(session) => {
            let sample = session.api().sync_clock().await?;
            Ok(RoundTripView {
                rtt_ms: sample.round_trip_ms,
            })
        }
    }
}
