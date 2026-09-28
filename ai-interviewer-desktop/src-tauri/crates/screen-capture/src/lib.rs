//! Screen capture for the Hirevion desktop app: every display through Windows Graphics
//! Capture, scaled and converted to NV12 on the GPU for the H.264 encoder.

pub mod geometry;

#[cfg(windows)]
pub mod capture;
#[cfg(windows)]
pub mod context;
#[cfg(windows)]
pub mod convert;
#[cfg(windows)]
pub mod device;
#[cfg(windows)]
pub mod monitors;
