//! Records the screen for a while and reports CPU, sizes and timings (SP-00d).
//!
//! cargo run --release -p hv-recorder --example capture_bench -- --seconds 60 --out <dir>
//! Defaults (ADR-0006): 15 fps, 10 s segments, up to 1920x1080, constant quality 50,
//! one keyframe per segment, hardware encoder when available.
//! Options: --fps --segment-seconds --max-width --max-height --quality 1-100
//!          --vbr --bitrate --gop-seconds --software --no-border --primary-only

use hv_recorder::bench::{self, BenchArgs};
use hv_recorder::process;
use hv_recorder::recorder::{DisplayReport, Recorder, RecorderConfig, SegmentRecord};
use hv_recorder::stats::{cpu_percent, percentile};
use hv_recorder::writer::RateControl;
use std::process::ExitCode;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use windows::Win32::UI::HiDpi::{
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, SetProcessDpiAwarenessContext,
};

fn main() -> ExitCode {
    let args = match bench::parse(std::env::args().skip(1)) {
        Ok(args) => args,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };
    // SAFETY: called once at startup, before any window or display query.
    let _ = unsafe { SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) };
    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("capture bench failed: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run(args: &BenchArgs) -> windows_core::Result<()> {
    let on_segment: Arc<dyn Fn(&SegmentRecord) + Send + Sync> = Arc::new(|record| {
        println!(
            "display {} segment {:06}: {} frames, {:.2} MB, finalize {:.0} ms{}",
            record.display,
            record.seq,
            record.frames,
            megabytes(record.bytes),
            record.finalize_ms,
            if record.valid_mp4 {
                ""
            } else {
                ", NOT A COMPLETE MP4"
            }
        );
    });
    let config = RecorderConfig {
        out_dir: args.out.clone(),
        fps: args.fps,
        segment_seconds: args.segment_seconds,
        max_size: args.max_size,
        bitrate: args.bitrate,
        rate_control: args.quality.map_or(RateControl::Vbr, RateControl::Quality),
        gop_seconds: args.gop_seconds,
        hardware: args.hardware,
        border: args.border,
        all_displays: args.all_displays,
        on_segment: Some(on_segment),
    };
    println!(
        "recording {} s at {} fps, {} s segments, {}, {} encoder -> {}",
        args.seconds,
        args.fps,
        args.segment_seconds,
        args.quality.map_or_else(
            || format!("{} bps VBR", args.bitrate),
            |level| format!("constant quality {level}")
        ),
        if args.hardware {
            "hardware-preferred"
        } else {
            "software"
        },
        args.out.display()
    );

    let cpu_start = process::cpu_snapshot()?;
    let started = Instant::now();
    let recorder = Recorder::start(config)?;
    thread::sleep(Duration::from_secs(args.seconds));
    let reports = recorder.stop();
    let elapsed = started.elapsed();
    let cpu_end = process::cpu_snapshot()?;

    for report in &reports {
        print_display(report, elapsed, args.fps);
    }
    let cpu = cpu_percent(
        cpu_end.cpu_ticks - cpu_start.cpu_ticks,
        cpu_end.at - cpu_start.at,
        process::logical_processors(),
    );
    println!(
        "process: {cpu:.1} % of {} logical processors, peak working set {:.0} MB",
        process::logical_processors(),
        megabytes(process::peak_working_set_bytes()?)
    );
    Ok(())
}

fn print_display(report: &DisplayReport, elapsed: Duration, fps: u32) {
    println!(
        "\ndisplay {} ({}) on {}",
        report.display, report.monitor, report.adapter
    );
    if let Some(error) = &report.error {
        println!("  ERROR: {error}");
    }
    println!(
        "  {}x{} -> {}x{}; {}",
        report.source.width,
        report.source.height,
        report.output.width,
        report.output.height,
        report.transforms
    );
    let expected = elapsed.as_secs_f64() * f64::from(fps);
    println!(
        "  frames: {} written (~{expected:.0} expected), {} repeated, {} delivered by Windows, \
         {} late ticks, {} resizes",
        report.frames_written,
        report.frames_repeated,
        report.frames_delivered,
        report.late_ticks,
        report.resized
    );
    print_timing("tick work", &report.tick_ms);
    print_timing("rotation", &report.rotate_ms);
    let finalize: Vec<f64> = report.segments.iter().map(|s| s.finalize_ms).collect();
    print_timing("finalize", &finalize);
    let bytes: usize = report.segments.iter().map(|s| s.bytes).sum();
    let valid = report.segments.iter().filter(|s| s.valid_mp4).count();
    let minutes = elapsed.as_secs_f64() / 60.0;
    println!(
        "  segments: {} ({valid} complete MP4s), {:.1} MB total, {:.1} MB per minute",
        report.segments.len(),
        megabytes(bytes),
        megabytes(bytes) / minutes.max(f64::EPSILON)
    );
}

fn print_timing(label: &str, values: &[f64]) {
    let (Some(p50), Some(p95)) = (percentile(values, 50.0), percentile(values, 95.0)) else {
        return;
    };
    let max = values.iter().copied().fold(0.0, f64::max);
    println!("  {label}: p50 {p50:.1} ms, p95 {p95:.1} ms, max {max:.1} ms");
}

#[allow(clippy::cast_precision_loss)] // Byte counts here are far below 2^52.
fn megabytes(bytes: usize) -> f64 {
    bytes as f64 / 1_048_576.0
}
