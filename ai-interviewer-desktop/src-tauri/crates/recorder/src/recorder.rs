//! The recording loop: one thread per display captures at a fixed rate, converts on the
//! GPU, encodes H.264 and rotates to a new MP4 segment every few seconds. Opening a
//! segment's encoder (about 350 ms for Intel Quick Sync) happens ahead of time on a helper
//! thread, and finished segments are hashed and saved by a finalizer thread, so the capture
//! loop never waits for either.

use crate::clock::FrameClock;
use crate::hash::{hex, sha256};
use crate::mp4::looks_like_mp4;
use crate::writer::{self, DeviceManager, EncoderConfig, RateControl, SegmentWriter};
use hv_screen_capture::capture::{CaptureOptions, CapturedFrame, MonitorCapture};
use hv_screen_capture::context::Context;
use hv_screen_capture::convert::Nv12Converter;
use hv_screen_capture::device::{GpuDevice, init_com_mta};
use hv_screen_capture::geometry::{Size, fit_even};
use hv_screen_capture::monitors::{self, MonitorInfo};
use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use windows::Win32::Foundation::{E_FAIL, E_INVALIDARG};
use windows_core::{Error, Result};

/// NV12 textures the converter cycles through. It must exceed the frames a hardware
/// encoder keeps in flight.
const CONVERTER_RING: usize = 8;

/// Called on the finalizer thread after each segment is saved.
pub type SegmentCallback = Arc<dyn Fn(&SegmentRecord) + Send + Sync>;

/// What to record.
#[derive(Clone)]
pub struct RecorderConfig {
    pub out_dir: PathBuf,
    pub fps: u32,
    pub segment_seconds: u32,
    pub max_size: Size,
    pub bitrate: u32,
    pub rate_control: RateControl,
    pub gop_seconds: u32,
    pub hardware: bool,
    pub border: bool,
    pub all_displays: bool,
    pub on_segment: Option<SegmentCallback>,
}

/// One finished segment on disk.
#[derive(Debug, Clone)]
pub struct SegmentRecord {
    pub display: usize,
    pub seq: u64,
    pub path: PathBuf,
    pub started_unix_ms: u128,
    pub frames: u32,
    pub bytes: usize,
    pub sha256: String,
    pub finalize_ms: f64,
    pub valid_mp4: bool,
}

/// Everything measured for one display.
#[derive(Debug, Clone, Default)]
pub struct DisplayReport {
    pub display: usize,
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
    pub error: Option<String>,
}

/// A running recorder; call [`Recorder::stop`] to finish the last segments.
pub struct Recorder {
    stop: Arc<AtomicBool>,
    threads: Vec<JoinHandle<DisplayReport>>,
}

impl Recorder {
    pub fn start(config: RecorderConfig) -> Result<Self> {
        if FrameClock::new(config.fps, config.segment_seconds).is_none() {
            return Err(Error::new(
                E_INVALIDARG,
                "fps and segment length must be positive",
            ));
        }
        let displays: Vec<MonitorInfo> = monitors::enumerate()?
            .into_iter()
            .filter(|monitor| config.all_displays || monitor.primary)
            .collect();
        let stop = Arc::new(AtomicBool::new(false));
        let threads = displays
            .into_iter()
            .enumerate()
            .map(|(display, monitor)| {
                let config = config.clone();
                let stop = Arc::clone(&stop);
                thread::spawn(move || record_display(display, &monitor, &config, &stop))
            })
            .collect();
        Ok(Self { stop, threads })
    }

    /// Stops every display, waits for the last segments to be saved and returns the reports.
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

struct Pending {
    seq: u64,
    started: SystemTime,
    writer: SegmentWriter,
}

fn record_display(
    display: usize,
    monitor: &MonitorInfo,
    config: &RecorderConfig,
    stop: &AtomicBool,
) -> DisplayReport {
    let mut report = DisplayReport {
        display,
        monitor: monitor.name.clone(),
        ..DisplayReport::default()
    };
    let dir = config.out_dir.join(format!("display-{display}"));
    let (to_finalizer, pending) = mpsc::channel::<Pending>();
    let finalizer = {
        let dir = dir.clone();
        let callback = config.on_segment.clone();
        thread::spawn(move || finalize_segments(display, &dir, &pending, callback.as_ref()))
    };
    if let Err(error) = capture_loop(monitor, config, stop, &dir, &to_finalizer, &mut report) {
        report.error = Some(error.message());
    }
    drop(to_finalizer);
    report.segments = finalizer.join().unwrap_or_default();
    report
}

fn capture_loop(
    monitor: &MonitorInfo,
    config: &RecorderConfig,
    stop: &AtomicBool,
    dir: &Path,
    to_finalizer: &mpsc::Sender<Pending>,
    report: &mut DisplayReport,
) -> Result<()> {
    init_com_mta().context("join the COM multithreaded apartment")?;
    writer::startup()?;
    fs::create_dir_all(dir).map_err(|error| Error::new(E_INVALIDARG, error.to_string()))?;
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
    let mut capture = MonitorCapture::start(&gpu, monitor.hmonitor(), options)?;
    let first = first_frame(&mut capture, Duration::from_secs(3))?;
    report.source = first.size;
    report.output = fit_even(first.size, config.max_size);
    let mut converter = Nv12Converter::new(&gpu, first.size, report.output, CONVERTER_RING)?;
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
    let mut segment_started = SystemTime::now();
    let start = Instant::now();
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
            let started = std::mem::replace(&mut segment_started, SystemTime::now());
            let _ = to_finalizer.send(Pending {
                seq: position.seq - 1,
                started,
                writer: finished,
            });
            report.rotate_ms.push(millis(rotation.elapsed()));
        }

        if let Some(captured) = capture.latest()? {
            if captured.size != converter.source_size() {
                // The display changed resolution: keep the encoder's size and rescale into it.
                converter = Nv12Converter::new(&gpu, captured.size, report.output, CONVERTER_RING)?;
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
            started: segment_started,
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

fn finalize_segments(
    display: usize,
    dir: &Path,
    pending: &mpsc::Receiver<Pending>,
    callback: Option<&SegmentCallback>,
) -> Vec<SegmentRecord> {
    let _ = init_com_mta();
    let mut records = Vec::new();
    for Pending {
        seq,
        started,
        writer,
    } in pending
    {
        let frames = writer.frames();
        let finalize = Instant::now();
        let Ok(bytes) = writer.finish() else {
            continue;
        };
        let finalize_ms = millis(finalize.elapsed());
        let path = dir.join(format!("{seq:06}.mp4"));
        if fs::write(&path, &bytes).is_err() {
            continue;
        }
        let record = SegmentRecord {
            display,
            seq,
            path,
            started_unix_ms: started
                .duration_since(UNIX_EPOCH)
                .map_or(0, |d| d.as_millis()),
            frames,
            bytes: bytes.len(),
            sha256: sha256(&bytes)
                .map(|digest| hex(&digest))
                .unwrap_or_default(),
            finalize_ms,
            valid_mp4: looks_like_mp4(&bytes),
        };
        append_manifest(dir, &record);
        if let Some(callback) = callback {
            callback(&record);
        }
        records.push(record);
    }
    records
}

fn append_manifest(dir: &Path, record: &SegmentRecord) {
    let line = format!(
        "{{\"display\":{},\"seq\":{},\"started_unix_ms\":{},\"frames\":{},\"bytes\":{},\
         \"sha256\":\"{}\",\"finalize_ms\":{:.1},\"valid_mp4\":{}}}\n",
        record.display,
        record.seq,
        record.started_unix_ms,
        record.frames,
        record.bytes,
        record.sha256,
        record.finalize_ms,
        record.valid_mp4
    );
    if let Ok(mut file) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("manifest.jsonl"))
    {
        let _ = file.write_all(line.as_bytes());
    }
}

fn millis(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1000.0
}
