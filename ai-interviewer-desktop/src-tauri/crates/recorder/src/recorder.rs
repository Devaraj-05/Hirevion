//! The screen recording service: one thread per display captures at a fixed rate, converts
//! on the GPU, encodes H.264 and rotates to a new MP4 segment every few seconds (ADR-0006).
//!
//! - Opening a segment's encoder (about 350 ms for Intel Quick Sync) happens ahead of time on
//!   a helper thread, so rotation never stalls capture.
//! - Finished segments are finalized on a separate thread and handed, still in memory, to a
//!   [`SegmentSink`] (the encrypted segment store). Nothing is written to disk unencrypted.
//! - Each segment carries its track (`screen-1` is the primary display), its seq (from 0) and
//!   its first frame's time in server milliseconds.

use crate::clock::FrameClock;
use crate::mp4::looks_like_mp4;
use crate::timeline::{duration_ms, screen_tracks, server_ms_at};
use crate::writer::{self, DeviceManager, EncoderConfig, RateControl, SegmentWriter};
use hv_screen_capture::capture::{CaptureOptions, CapturedFrame, MonitorCapture};
use hv_screen_capture::context::Context;
use hv_screen_capture::convert::Nv12Converter;
use hv_screen_capture::device::{GpuDevice, init_com_mta};
use hv_screen_capture::geometry::{Size, fit_even};
use hv_screen_capture::monitors::{self, MonitorInfo};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use windows::Win32::Foundation::{E_FAIL, E_INVALIDARG};
use windows_core::{Error, Result};

/// The server's clock: milliseconds since the Unix epoch (the API client's
/// `server_now_ms`). Segment start times are stamped with it.
pub type ServerClock = Arc<dyn Fn() -> i64 + Send + Sync>;

/// Receives finished segments, on each display's finalizer thread.
pub trait SegmentSink: Send + Sync {
    /// A complete segment. Store it (encrypted) quickly: the next one follows in seconds.
    fn segment(&self, segment: RecordedSegment);

    /// A display stopped recording (capture or encoder failure). Its finished segments were
    /// already delivered.
    fn display_failed(&self, track: &str, error: &str) {
        let _ = (track, error);
    }
}

/// What to record. The defaults are ADR-0006's measured settings.
#[derive(Debug, Clone)]
pub struct RecorderConfig {
    pub fps: u32,
    pub segment_seconds: u32,
    pub max_size: Size,
    pub bitrate: u32,
    pub rate_control: RateControl,
    pub gop_seconds: u32,
    pub hardware: bool,
    pub border: bool,
    pub all_displays: bool,
    /// NV12 textures the converter cycles through; must exceed the frames a hardware
    /// encoder keeps in flight.
    pub converter_ring: usize,
}

impl Default for RecorderConfig {
    fn default() -> Self {
        Self {
            fps: 15,
            segment_seconds: 10,
            max_size: Size {
                width: 1920,
                height: 1080,
            },
            bitrate: 1_500_000,
            // Constant quality 50 with one keyframe per segment.
            rate_control: RateControl::Quality(50),
            gop_seconds: 10,
            hardware: true,
            border: true,
            all_displays: true,
            converter_ring: 8,
        }
    }
}

/// One finished segment, in memory.
pub struct RecordedSegment {
    /// `screen-1`, `screen-2`, …
    pub track: String,
    /// The display's index in Windows' order.
    pub display: usize,
    /// From 0 per track.
    pub seq: u64,
    /// The first frame's time, in server milliseconds.
    pub started_at_ms: i64,
    pub duration_ms: u32,
    pub frames: u32,
    /// The MP4 file.
    pub bytes: Vec<u8>,
    pub finalize_ms: f64,
    pub valid_mp4: bool,
}

impl std::fmt::Debug for RecordedSegment {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RecordedSegment")
            .field("track", &self.track)
            .field("seq", &self.seq)
            .field("started_at_ms", &self.started_at_ms)
            .field("duration_ms", &self.duration_ms)
            .field("frames", &self.frames)
            .field("bytes", &self.bytes.len())
            .field("valid_mp4", &self.valid_mp4)
            .finish_non_exhaustive()
    }
}

/// A segment's description, kept in the report.
#[derive(Debug, Clone)]
pub struct SegmentRecord {
    pub track: String,
    pub seq: u64,
    pub started_at_ms: i64,
    pub duration_ms: u32,
    pub frames: u32,
    pub bytes: usize,
    pub finalize_ms: f64,
    pub valid_mp4: bool,
}

/// Everything measured for one display.
#[derive(Debug, Clone, Default)]
pub struct DisplayReport {
    pub display: usize,
    pub track: String,
    pub monitor: String,
    pub adapter: String,
    pub source: Size,
    pub output: Size,
    pub transforms: String,
    pub frames_written: u64,
    /// Ticks where the screen hadn't changed, so the previous frame was written again.
    pub frames_repeated: u64,
    /// Frames Windows delivered (it may deliver more often than we encode).
    pub frames_delivered: u64,
    pub resized: u64,
    /// Ticks that started more than one frame interval late.
    pub late_ticks: u64,
    /// Capture + convert + encode-submit time per tick.
    pub tick_ms: Vec<f64>,
    /// Time to open the next segment's writer at each rotation.
    pub rotate_ms: Vec<f64>,
    pub segments: Vec<SegmentRecord>,
    /// Segments whose MP4 couldn't be finished.
    pub failed_segments: u64,
    pub error: Option<String>,
}

/// A running recording of every display; call [`Recorder::stop`] to finish the last
/// segments.
pub struct Recorder {
    stop: Arc<AtomicBool>,
    threads: Vec<JoinHandle<DisplayReport>>,
    tracks: Vec<String>,
}

impl Recorder {
    /// Starts one recording thread per display (or only the primary one).
    pub fn start(
        config: RecorderConfig,
        sink: Arc<dyn SegmentSink>,
        clock: ServerClock,
    ) -> Result<Self> {
        if FrameClock::new(config.fps, config.segment_seconds).is_none() {
            return Err(Error::new(
                E_INVALIDARG,
                "fps and segment length must be positive",
            ));
        }
        let displays = monitors::enumerate()?;
        let primary: Vec<bool> = displays.iter().map(|monitor| monitor.primary).collect();
        let stop = Arc::new(AtomicBool::new(false));
        let mut threads = Vec::new();
        let mut tracks = Vec::new();
        for (display, track) in screen_tracks(&primary) {
            if !config.all_displays && !displays[display].primary {
                continue;
            }
            let monitor = displays[display].clone();
            let job = DisplayJob {
                display,
                track: track.clone(),
                monitor,
                config: config.clone(),
                sink: Arc::clone(&sink),
                clock: Arc::clone(&clock),
            };
            let stop = Arc::clone(&stop);
            threads.push(thread::spawn(move || record_display(job, &stop)));
            tracks.push(track);
        }
        Ok(Self {
            stop,
            threads,
            tracks,
        })
    }

    /// The tracks being recorded, `screen-1` first.
    #[must_use]
    pub fn tracks(&self) -> &[String] {
        &self.tracks
    }

    /// Whether every display thread is still recording.
    #[must_use]
    pub fn is_recording(&self) -> bool {
        !self.threads.iter().any(JoinHandle::is_finished)
    }

    /// Stops every display, waits for the last segments to reach the sink and returns the
    /// reports.
    #[must_use]
    pub fn stop(self) -> Vec<DisplayReport> {
        self.stop.store(true, Ordering::Relaxed);
        self.threads
            .into_iter()
            .map(|thread| {
                thread.join().unwrap_or_else(|_| DisplayReport {
                    error: Some(String::from("the display thread panicked")),
                    ..DisplayReport::default()
                })
            })
            .collect()
    }
}

struct DisplayJob {
    display: usize,
    track: String,
    monitor: MonitorInfo,
    config: RecorderConfig,
    sink: Arc<dyn SegmentSink>,
    clock: ServerClock,
}

struct Pending {
    seq: u64,
    started_at_ms: i64,
    writer: SegmentWriter,
}

fn record_display(job: DisplayJob, stop: &AtomicBool) -> DisplayReport {
    let mut report = DisplayReport {
        display: job.display,
        track: job.track.clone(),
        monitor: job.monitor.name.clone(),
        ..DisplayReport::default()
    };
    let (to_finalizer, pending) = mpsc::channel::<Pending>();
    let finalizer = {
        let track = job.track.clone();
        let sink = Arc::clone(&job.sink);
        let frame_clock = FrameClock::new(job.config.fps, job.config.segment_seconds);
        thread::spawn(move || finalize_segments(&track, job.display, frame_clock, &pending, &*sink))
    };
    let result = capture_loop(&job, stop, &to_finalizer, &mut report);
    drop(to_finalizer);
    let (segments, failed) = finalizer.join().unwrap_or_default();
    report.segments = segments;
    report.failed_segments = failed;
    if let Err(error) = result {
        let message = error.message();
        job.sink.display_failed(&job.track, &message);
        report.error = Some(message);
    }
    report
}

fn capture_loop(
    job: &DisplayJob,
    stop: &AtomicBool,
    to_finalizer: &mpsc::Sender<Pending>,
    report: &mut DisplayReport,
) -> Result<()> {
    let config = &job.config;
    init_com_mta().context("join the COM multithreaded apartment")?;
    writer::startup()?;
    let clock = FrameClock::new(config.fps, config.segment_seconds)
        .ok_or_else(|| Error::new(E_INVALIDARG, "fps and segment length must be positive"))?;
    let interval = Duration::from_secs(1) / config.fps;

    let gpu = GpuDevice::new().context("create D3D11 device")?;
    report.adapter = gpu.adapter_name().to_owned();
    let manager = writer::device_manager(&gpu)?;
    let options = CaptureOptions {
        cursor: true,
        border: config.border,
        min_interval: Some(interval),
    };
    let mut capture = MonitorCapture::start(&gpu, job.monitor.hmonitor(), options)?;
    let first = first_frame(&mut capture, Duration::from_secs(3))?;
    report.source = first.size;
    report.output = fit_even(first.size, config.max_size);
    let ring = config.converter_ring.max(2);
    let mut converter = Nv12Converter::new(&gpu, first.size, report.output, ring)?;
    let mut current = converter.convert(&first.texture)?;
    drop(first);

    let encoder = EncoderConfig {
        size: report.output,
        fps: config.fps,
        bitrate: config.bitrate,
        rate_control: config.rate_control,
        gop_frames: config.fps * config.gop_seconds,
        hardware: config.hardware,
    };
    let writers = WriterFactory::start(manager, encoder);
    let mut writer = writers.take()?;
    report.transforms = writer.transforms().to_owned();
    let start = Instant::now();
    let origin_ms = (job.clock)();
    let mut segment_started_ms = origin_ms;
    let mut frame: u64 = 0;

    while !stop.load(Ordering::Relaxed) {
        let offset = u64::try_from(clock.sample_time(frame)).unwrap_or(0) * 100;
        let due = start + Duration::from_nanos(offset);
        let now = Instant::now();
        if due > now {
            thread::sleep(due - now);
        } else if now - due > interval {
            report.late_ticks += 1;
        }
        let work = Instant::now();

        let position = clock.position(frame);
        if position.index == 0 && frame > 0 {
            let rotation = Instant::now();
            let next = writers.take()?;
            let finished = std::mem::replace(&mut writer, next);
            let started_at_ms = std::mem::replace(
                &mut segment_started_ms,
                server_ms_at(origin_ms, start, work),
            );
            let _ = to_finalizer.send(Pending {
                seq: position.seq - 1,
                started_at_ms,
                writer: finished,
            });
            report.rotate_ms.push(millis(rotation.elapsed()));
        }

        if let Some(captured) = capture.latest()? {
            if captured.size != converter.source_size() {
                // The display changed resolution: keep the encoder's size and rescale into it.
                converter = Nv12Converter::new(&gpu, captured.size, report.output, ring)?;
            }
            current = converter.convert(&captured.texture)?;
        } else {
            report.frames_repeated += 1;
        }
        writer.write(
            &current,
            clock.segment_time(frame),
            clock.frame_duration(frame),
        )?;
        report.frames_written += 1;
        report.tick_ms.push(millis(work.elapsed()));
        frame += 1;
    }

    if writer.frames() > 0 {
        let seq = clock.position(frame.saturating_sub(1)).seq;
        let _ = to_finalizer.send(Pending {
            seq,
            started_at_ms: segment_started_ms,
            writer,
        });
    }
    report.frames_delivered = capture.delivered;
    report.resized = capture.resized;
    Ok(())
}

/// Keeps one segment writer opened in advance on a helper thread.
struct WriterFactory {
    requests: Option<mpsc::Sender<()>>,
    ready: mpsc::Receiver<Result<SegmentWriter>>,
    thread: Option<JoinHandle<()>>,
}

impl WriterFactory {
    fn start(manager: DeviceManager, config: EncoderConfig) -> Self {
        let (requests, wanted) = mpsc::channel::<()>();
        let (made, ready) = mpsc::channel();
        let thread = thread::spawn(move || {
            let _ = init_com_mta();
            for () in wanted {
                if made.send(SegmentWriter::new(&manager, &config)).is_err() {
                    return;
                }
            }
        });
        let _ = requests.send(());
        Self {
            requests: Some(requests),
            ready,
            thread: Some(thread),
        }
    }

    /// The writer prepared in advance (waiting for it if it isn't ready yet); asks for the
    /// next one straight away.
    fn take(&self) -> Result<SegmentWriter> {
        let writer = self
            .ready
            .recv()
            .map_err(|_| Error::new(E_FAIL, "the writer factory stopped"))?
            .context("open segment writer")?;
        if let Some(requests) = &self.requests {
            let _ = requests.send(());
        }
        Ok(writer)
    }
}

impl Drop for WriterFactory {
    fn drop(&mut self) {
        // Closing the request channel ends the helper thread; an unused spare writer is
        // dropped with the receiver.
        self.requests = None;
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

fn first_frame(capture: &mut MonitorCapture, timeout: Duration) -> Result<CapturedFrame> {
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(frame) = capture.latest()? {
            return Ok(frame);
        }
        if Instant::now() > deadline {
            return Err(Error::new(
                E_INVALIDARG,
                "no frame from Windows Graphics Capture",
            ));
        }
        thread::sleep(Duration::from_millis(5));
    }
}

/// Finishes each segment's MP4 and hands it to the sink. Returns the descriptions and the
/// number of segments that couldn't be finished.
fn finalize_segments(
    track: &str,
    display: usize,
    clock: Option<FrameClock>,
    pending: &mpsc::Receiver<Pending>,
    sink: &dyn SegmentSink,
) -> (Vec<SegmentRecord>, u64) {
    let _ = init_com_mta();
    let mut records = Vec::new();
    let mut failed = 0;
    for Pending {
        seq,
        started_at_ms,
        writer,
    } in pending
    {
        let frames = writer.frames();
        let finalize = Instant::now();
        let Ok(bytes) = writer.finish() else {
            failed += 1;
            continue;
        };
        let record = SegmentRecord {
            track: track.to_owned(),
            seq,
            started_at_ms,
            duration_ms: clock.map_or(0, |clock| duration_ms(&clock, frames)),
            frames,
            bytes: bytes.len(),
            finalize_ms: millis(finalize.elapsed()),
            valid_mp4: looks_like_mp4(&bytes),
        };
        sink.segment(RecordedSegment {
            track: record.track.clone(),
            display,
            seq,
            started_at_ms,
            duration_ms: record.duration_ms,
            frames,
            bytes,
            finalize_ms: record.finalize_ms,
            valid_mp4: record.valid_mp4,
        });
        records.push(record);
    }
    (records, failed)
}

fn millis(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1000.0
}
