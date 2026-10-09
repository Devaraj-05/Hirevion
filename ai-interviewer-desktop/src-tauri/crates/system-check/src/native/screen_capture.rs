//! The screen-capture probe: one frame from every display through Windows Graphics Capture.

use super::com::Mta;
use super::describe;
use crate::classify::{FrameOutcome, MonitorProbe, classify_screen_capture};
use crate::result::{CheckResult, Status, names};
use hv_screen_capture::capture::{CaptureOptions, MonitorCapture};
use hv_screen_capture::device::GpuDevice;
use hv_screen_capture::monitors;
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant};

/// How long every display has to deliver its first frame.
pub(crate) const FRAME_TIMEOUT: Duration = Duration::from_secs(2);
/// Extra time for start-up (GPU device, capture sessions) before the probe is abandoned.
const START_UP_ALLOWANCE: Duration = Duration::from_secs(3);
const POLL_INTERVAL: Duration = Duration::from_millis(15);

/// Runs the probe on its own COM thread and waits at most [`FRAME_TIMEOUT`] plus
/// [`START_UP_ALLOWANCE`] for it.
pub(crate) fn probe() -> CheckResult {
    let (sender, receiver) = mpsc::channel();
    let spawned = std::thread::Builder::new()
        .name("hv-screen-capture-probe".to_owned())
        .spawn(move || {
            let _ = sender.send(run());
        });
    if let Err(error) = spawned {
        return unavailable(&error.to_string());
    }
    match receiver.recv_timeout(FRAME_TIMEOUT + START_UP_ALLOWANCE) {
        Ok(result) => result,
        Err(RecvTimeoutError::Timeout) => unavailable("Windows did not respond in time"),
        Err(RecvTimeoutError::Disconnected) => unavailable("the probe stopped unexpectedly"),
    }
}

fn run() -> CheckResult {
    let _com = match Mta::join() {
        Ok(com) => com,
        Err(error) => return unavailable(&describe(&error)),
    };
    // Every capture object is dropped inside capture_all, before COM is left.
    match capture_all() {
        Ok(probes) => classify_screen_capture(&probes, FRAME_TIMEOUT),
        Err(error) => unavailable(&describe(&error)),
    }
}

fn capture_all() -> windows::core::Result<Vec<MonitorProbe>> {
    let displays = monitors::enumerate()?;
    if displays.is_empty() {
        return Ok(Vec::new());
    }
    let gpu = GpuDevice::new()?;
    let options = CaptureOptions {
        cursor: false,
        border: false,
        min_interval: None,
    };
    let mut sessions: Vec<_> = displays
        .iter()
        .map(|display| MonitorCapture::start(&gpu, display.hmonitor(), options))
        .collect();
    let mut outcomes: Vec<Option<FrameOutcome>> = sessions
        .iter()
        .map(|session| {
            session
                .as_ref()
                .err()
                .map(|error| FrameOutcome::Error(describe(error)))
        })
        .collect();

    let deadline = Instant::now() + FRAME_TIMEOUT;
    loop {
        for (session, outcome) in sessions.iter_mut().zip(outcomes.iter_mut()) {
            if outcome.is_some() {
                continue;
            }
            let Ok(capture) = session else {
                continue;
            };
            match capture.latest() {
                Ok(Some(_frame)) => *outcome = Some(FrameOutcome::Frame),
                Ok(None) => {}
                Err(error) => *outcome = Some(FrameOutcome::Error(describe(&error))),
            }
        }
        if outcomes.iter().all(Option::is_some) || Instant::now() >= deadline {
            break;
        }
        std::thread::sleep(POLL_INTERVAL);
    }
    drop(sessions);

    Ok(displays
        .into_iter()
        .zip(outcomes)
        .map(|(display, outcome)| MonitorProbe {
            name: display.name,
            outcome: outcome.unwrap_or(FrameOutcome::NoFrame),
        })
        .collect())
}

fn unavailable(reason: &str) -> CheckResult {
    CheckResult::new(names::SCREEN_CAPTURE, Status::Fail)
        .with_value("unavailable")
        .with_detail(format!("Screen capture is unavailable: {reason}"))
}
