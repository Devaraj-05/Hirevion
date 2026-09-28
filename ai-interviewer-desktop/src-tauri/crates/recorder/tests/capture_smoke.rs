//! Records the primary display for about three seconds. Needs an interactive desktop and a
//! GPU, so it is ignored by default:
//!     cargo test -p hv-recorder --test capture_smoke -- --ignored

#![cfg(windows)]

use hv_recorder::mp4::looks_like_mp4;
use hv_recorder::recorder::{Recorder, RecorderConfig};
use hv_recorder::writer::RateControl;
use hv_screen_capture::geometry::Size;
use std::time::Duration;

#[test]
#[ignore = "needs an interactive desktop and a GPU"]
fn records_one_second_segments_of_the_primary_display() {
    let out = std::env::temp_dir().join(format!("hv-capture-smoke-{}", std::process::id()));
    let config = RecorderConfig {
        out_dir: out.clone(),
        fps: 15,
        segment_seconds: 1,
        max_size: Size {
            width: 1920,
            height: 1080,
        },
        bitrate: 1_500_000,
        rate_control: RateControl::Vbr,
        gop_seconds: 1,
        hardware: true,
        border: true,
        all_displays: false,
        on_segment: None,
    };

    let recorder = Recorder::start(config).expect("recorder starts");
    // Start-up (GPU device, capture session, first frame, encoder) takes under a second.
    std::thread::sleep(Duration::from_millis(4_500));
    let reports = recorder.stop();

    assert_eq!(reports.len(), 1, "only the primary display is recorded");
    let report = &reports[0];
    assert!(
        report.error.is_none(),
        "recording failed: {:?}",
        report.error
    );
    assert!(
        report.segments.len() >= 3,
        "only {} segments",
        report.segments.len()
    );
    for segment in &report.segments {
        let bytes = std::fs::read(&segment.path).expect("segment saved");
        assert!(
            looks_like_mp4(&bytes),
            "{} is not a complete MP4",
            segment.path.display()
        );
        assert_eq!(bytes.len(), segment.bytes);
    }
    let frames: u32 = report.segments.iter().map(|segment| segment.frames).sum();
    assert_eq!(
        u64::from(frames),
        report.frames_written,
        "every encoded frame is in a saved segment"
    );
    assert!(
        frames >= 45,
        "only {frames} frames; expected 3+ seconds at 15 fps"
    );
    let _ = std::fs::remove_dir_all(out);
}
