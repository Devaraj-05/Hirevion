//! Real screen captures. They need an interactive desktop and a GPU, so they are ignored by
//! default; run them on the development PC with
//!     cargo test -p hv-recorder --test capture_smoke -- --ignored --test-threads=1

#![cfg(windows)]

use hv_recorder::mp4::looks_like_mp4;
use hv_recorder::recorder::{RecordedSegment, Recorder, RecorderConfig, SegmentSink, ServerClock};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Default)]
struct Collect {
    segments: Mutex<Vec<RecordedSegment>>,
    failures: Mutex<Vec<String>>,
}

impl SegmentSink for Collect {
    fn segment(&self, segment: RecordedSegment) {
        self.segments.lock().expect("lock").push(segment);
    }

    fn display_failed(&self, track: &str, error: &str) {
        self.failures
            .lock()
            .expect("lock")
            .push(format!("{track}: {error}"));
    }
}

/// A fake server clock running 5 s ahead of local time.
fn server_clock() -> ServerClock {
    Arc::new(|| local_ms() + 5_000)
}

fn local_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_millis()).expect("fits"))
}

#[test]
#[ignore = "needs an interactive desktop and a GPU; about 12 s"]
fn records_a_ten_second_segment_of_the_primary_display() {
    let sink = Arc::new(Collect::default());
    let config = RecorderConfig {
        all_displays: false,
        ..RecorderConfig::default()
    };
    let before = local_ms() + 5_000;
    let recorder = Recorder::start(config, sink.clone(), server_clock()).expect("recorder starts");
    assert_eq!(recorder.tracks(), ["screen-1"]);
    // Start-up (GPU device, capture session, first frame, encoder) takes under a second.
    std::thread::sleep(Duration::from_millis(11_500));
    assert!(recorder.is_recording());
    let reports = recorder.stop();

    assert!(sink.failures.lock().expect("lock").is_empty());
    let report = &reports[0];
    assert!(report.error.is_none(), "{:?}", report.error);
    let segments = sink.segments.lock().expect("lock");
    let first = segments.iter().find(|s| s.seq == 0).expect("segment 0");
    assert_eq!(first.track, "screen-1");
    assert_eq!(first.frames, 150, "exactly 10 s at 15 fps");
    assert_eq!(first.duration_ms, 10_000);
    assert!(first.valid_mp4 && looks_like_mp4(&first.bytes));
    assert!(
        (first.started_at_ms - before).abs() < 2_000,
        "stamped in server time: {} vs {before}",
        first.started_at_ms
    );
    // Constant quality 50 at 1080p: well under the contract's 50 MB.
    assert!(
        first.bytes.len() < 20_000_000,
        "{} bytes",
        first.bytes.len()
    );
    let frames: u32 = segments.iter().map(|s| s.frames).sum();
    assert_eq!(u64::from(frames), report.frames_written);
    if let Some(second) = segments.iter().find(|s| s.seq == 1) {
        let gap = second.started_at_ms - first.started_at_ms;
        assert!((gap - 10_000).abs() < 100, "segments 10 s apart: {gap}");
    }
}

#[test]
#[ignore = "needs an interactive desktop and a GPU"]
fn records_one_second_segments_of_every_display() {
    let sink = Arc::new(Collect::default());
    let config = RecorderConfig {
        segment_seconds: 1,
        gop_seconds: 1,
        ..RecorderConfig::default()
    };
    let recorder = Recorder::start(config, sink.clone(), server_clock()).expect("recorder starts");
    let tracks = recorder.tracks().to_vec();
    std::thread::sleep(Duration::from_millis(4_500));
    let reports = recorder.stop();

    assert_eq!(tracks[0], "screen-1");
    let segments = sink.segments.lock().expect("lock");
    for report in &reports {
        assert!(
            report.error.is_none(),
            "{}: {:?}",
            report.track,
            report.error
        );
        let mine: Vec<&RecordedSegment> = segments
            .iter()
            .filter(|s| s.track == report.track)
            .collect();
        assert!(
            mine.len() >= 3,
            "{}: only {} segments",
            report.track,
            mine.len()
        );
        assert!(mine.iter().all(|s| s.valid_mp4));
        let seqs: Vec<u64> = mine.iter().map(|s| s.seq).collect();
        let expected: Vec<u64> = (0..seqs.len() as u64).collect();
        assert_eq!(seqs, expected, "seq starts at 0 and has no gaps");
        let frames: u32 = mine.iter().map(|s| s.frames).sum();
        assert_eq!(u64::from(frames), report.frames_written);
    }
}
