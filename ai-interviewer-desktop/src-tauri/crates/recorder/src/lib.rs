//! H.264 screen recording for the Hirevion desktop app: frames paced to a fixed rate and
//! written as independent, fixed-length MP4 segments.

pub mod bench;
pub mod clock;
pub mod mp4;
pub mod stats;

#[cfg(windows)]
pub mod hash;
#[cfg(windows)]
pub mod process;
#[cfg(windows)]
pub mod recorder;
#[cfg(windows)]
pub mod writer;
