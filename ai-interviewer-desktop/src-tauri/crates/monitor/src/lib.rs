//! Native Windows monitoring for the Hirevion desktop app (PRD §60–63, master plan §6.12).
//!
//! [`Monitor::start`] runs the watchers on their own threads and sends [`Observation`]s over a
//! channel:
//!
//! - **processes** (polled): name, PID, path, publisher and signature, SHA-256, start time and
//!   window titles, with starts, exits and title changes;
//! - **focus** (a `SetWinEventHook` message loop): foreground changes and minimise/restore;
//! - **environment** (polled): displays, cameras and microphones (virtual ones flagged),
//!   windows hidden from capture, overlays, remote sessions and debuggers;
//! - **once at start:** the hypervisor check and the integrity findings the app hands in.
//!
//! The monitor observes and never judges: policy and severity live in `hv-event-queue` and on
//! the server. It never observes the keyboard (a test enforces that).

pub mod file_cache;
mod monitor;
#[cfg(windows)]
mod native;
mod observation;
pub mod track;
mod virtual_devices;

pub use monitor::{Clock, Monitor, MonitorConfig, MonitorHandle, Watch, system_clock};
pub use observation::{
    AppRef, CaptureDevice, DeviceChange, DeviceChangeKind, DeviceKind, DisplayChange,
    DisplayChangeKind, DisplayInfo, FocusChange, IntegrityFinding, MinimizeChange, Observation,
    ProcessInfo, RemoteSession, SignatureInfo, SignatureKind, SignatureStatus, VirtualDeviceFound,
    VirtualMachine, WindowSighting,
};
pub use virtual_devices::{DEFAULT_VIRTUAL_DEVICE_NAMES, VirtualDeviceCatalogue};
