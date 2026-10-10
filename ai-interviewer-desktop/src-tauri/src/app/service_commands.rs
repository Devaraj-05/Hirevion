//! The commands for the interview services (see `services`): start and stop, the proctoring
//! hooks the webview feeds, camera and microphone segments, and the upload progress.

use serde::Serialize;
use tauri::http::HeaderMap;
use tauri::ipc::{InvokeBody, Request};
use tauri::{AppHandle, Emitter, State};

use super::error::{CommandError, CommandResult};
use super::proctoring::{FaceEvent, startup_integrity};
use super::progress::UploadProgress;
use super::services::{Notify, ServicesStarted, StopMode, StoredSegmentView};
use super::state::AppState;

/// Starts the proctor session, the native monitor and recording for an interview. The
/// webview calls it once it has joined (or, in text mode, right after `start`), and may call
/// it again to fill in a part that failed (`problems`).
#[tauri::command]
pub async fn services_start(
    app: AppHandle,
    state: State<'_, AppState>,
    interview_id: String,
) -> CommandResult<ServicesStarted> {
    let notify: Notify = std::sync::Arc::new(move |event, payload| {
        let _ = app.emit(event, payload);
    });
    let integrity = startup_integrity(&state.integrity_variables, state.debugger_present);
    state.services.start(notify, &interview_id, integrity).await
}

/// Ends monitoring and screen recording; what's left uploads in the background
/// (`upload_progress`). Call it before `complete`, so the last events go out while the
/// proctor session is still open.
#[tauri::command]
pub async fn services_stop(state: State<'_, AppState>) -> CommandResult<()> {
    state.services.stop(StopMode::Complete).await;
    Ok(())
}

/// The camera and microphone the interview uses, as their labels (`MediaDeviceInfo.label`);
/// `null` for one that isn't capturing.
#[tauri::command]
pub async fn proctoring_set_devices(
    state: State<'_, AppState>,
    camera: Option<String>,
    mic: Option<String>,
) -> CommandResult<()> {
    state.services.set_devices(camera, mic)
}

/// A camera event from the face module (no `seq`; the queue numbers it).
#[tauri::command]
pub async fn proctoring_enqueue(state: State<'_, AppState>, event: FaceEvent) -> CommandResult<()> {
    state.services.enqueue_face_event(event).map(|_| ())
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct RecordingClockView {
    /// Server time minus this PC's time, in milliseconds.
    pub server_offset_ms: i64,
}

#[tauri::command]
pub async fn recording_clock(state: State<'_, AppState>) -> CommandResult<RecordingClockView> {
    Ok(RecordingClockView {
        server_offset_ms: state.services.clock_offset_ms().await,
    })
}

/// A header lookup by lower-case name, for `hv_segment_store::webview::segment_from_headers`.
fn header_lookup(headers: &HeaderMap) -> impl Fn(&str) -> Option<String> + '_ {
    move |name| {
        headers
            .get(name)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned)
    }
}

/// One finished camera or microphone segment: the raw bytes as the body, described by the
/// `x-hv-*` headers. The interview is the one Rust is recording, never the webview's say.
#[tauri::command]
pub async fn recording_store_segment(
    state: State<'_, AppState>,
    request: Request<'_>,
) -> CommandResult<StoredSegmentView> {
    let InvokeBody::Raw(bytes) = request.body() else {
        return Err(CommandError::new(
            "invalid-segment",
            "the segment must be sent as raw bytes".to_owned(),
        ));
    };
    state
        .services
        .store_segment(header_lookup(request.headers()), bytes)
        .await
}

/// How much of the interview's recording the server has acknowledged.
#[tauri::command]
pub async fn upload_progress(
    state: State<'_, AppState>,
    interview_id: String,
) -> CommandResult<UploadProgress> {
    state.services.upload_progress(&interview_id)
}

#[cfg(test)]
mod tests {
    use tauri::http::HeaderValue;

    use super::*;

    #[test]
    fn headers_are_found_by_lower_case_name() {
        let mut headers = HeaderMap::new();
        headers.insert("X-HV-Track", HeaderValue::from_static("camera"));
        headers.insert("x-hv-seq", HeaderValue::from_static("4"));
        let lookup = header_lookup(&headers);
        assert_eq!(lookup("x-hv-track").as_deref(), Some("camera"));
        assert_eq!(lookup("x-hv-seq").as_deref(), Some("4"));
        assert_eq!(lookup("x-hv-codec"), None);
    }

    #[test]
    fn the_webview_headers_make_a_segment_for_the_recorded_interview() {
        use hv_segment_store::Track;
        use hv_segment_store::webview::segment_from_headers;

        let mut headers = HeaderMap::new();
        for (name, value) in [
            ("x-hv-track", "mic"),
            ("x-hv-seq", "2"),
            ("x-hv-started-at-ms", "1760245400123"),
            ("x-hv-duration-ms", "10000"),
            ("x-hv-container", "webm"),
            ("x-hv-codec", "opus"),
        ] {
            headers.insert(name, HeaderValue::from_static(value));
        }
        let interview = "0192f3a4-5b6c-7d8e-9fa0-b1c2d3e4f5a6";
        let segment = segment_from_headers(interview, header_lookup(&headers)).expect("valid");
        assert_eq!(segment.track, Track::Mic);
        assert_eq!(segment.interview_id, interview);
        assert_eq!(segment.seq, 2);
    }
}
