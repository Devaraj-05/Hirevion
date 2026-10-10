//! H.264 screen recording for the Hirevion desktop app (ADR-0006): every display, frames paced
//! to a fixed rate and cut into independent 10-second MP4 segments that are handed, in memory,
//! to a [`recorder::SegmentSink`] (the encrypted segment store) with their track, seq and
//! server-time start.

pub mod bench;
pub mod clock;
pub mod mp4;
pub mod stats;
pub mod timeline;

#[cfg(windows)]
pub mod hash;
#[cfg(windows)]
pub mod process;
#[cfg(windows)]
pub mod recorder;
#[cfg(windows)]
pub mod writer;
