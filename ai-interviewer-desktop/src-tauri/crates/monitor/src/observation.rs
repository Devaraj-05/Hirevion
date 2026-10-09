//! What the monitor reports. Every timestamp (`*_ms`) is milliseconds since the Unix epoch on
//! the clock handed to the monitor (server time in the app).

use serde::Serialize;

/// One thing the monitor saw.
///
/// Most variants feed exactly one event of `docs/api/contracts/proctoring.md` (see
/// [`Observation::contract_event`]); the process variants feed the policy matcher, which turns
/// a match into `BLOCKED_PROCESS_DETECTED`.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Observation {
    /// A process is running: seen at start (`at_start`) or started since the last poll (§60).
    ProcessStarted {
        at_ms: i64,
        at_start: bool,
        process: ProcessInfo,
    },
    /// A process ended.
    ProcessExited { at_ms: i64, pid: u32, name: String },
    /// The visible top-level window titles of a running process changed.
    ProcessWindowsChanged {
        at_ms: i64,
        pid: u32,
        window_titles: Vec<String>,
    },
    /// The foreground window moved to another process (§62).
    FocusChanged(FocusChange),
    /// A top-level window was minimised or restored (§62).
    Minimize(MinimizeChange),
    /// A display was connected, disconnected or reconfigured, or several were present at
    /// start (§63).
    DisplayChanged(DisplayChange),
    /// A camera or microphone was connected or disconnected (§63).
    DeviceChanged(DeviceChange),
    /// A capture device whose name says it is virtual (OBS Virtual Camera, VB-Cable…).
    VirtualDevice(VirtualDeviceFound),
    /// A visible window of another process is hidden from screen capture.
    CaptureExcludedWindow(WindowSighting),
    /// A visible topmost, layered window of another process: an overlay (§62 "unexpected
    /// window"). The contract has no event for it yet, so it isn't sent.
    OverlayWindow(WindowSighting),
    /// The session is remote (RDP) or remotely controlled.
    RemoteSession(RemoteSession),
    /// A hypervisor is present (evidence only).
    VirtualMachine(VirtualMachine),
    /// A debugger or a WebView2 override was found.
    ClientIntegrity(IntegrityFinding),
}

impl Observation {
    /// The contract event this observation is reported as, when it maps to one directly.
    ///
    /// `None` for process changes (the policy matcher decides), overlays (no contract event
    /// yet) and devices (the event depends on which device the interview uses).
    pub fn contract_event(&self) -> Option<&'static str> {
        match self {
            Self::FocusChanged(_) => Some("APPLICATION_FOCUS_CHANGE"),
            Self::Minimize(_) => Some("WINDOW_MINIMIZED"),
            Self::DisplayChanged(_) => Some("EXTERNAL_DISPLAY_CHANGE"),
            Self::VirtualDevice(_) => Some("VIRTUAL_DEVICE_DETECTED"),
            Self::CaptureExcludedWindow(_) => Some("CAPTURE_EXCLUDED_WINDOW"),
            Self::RemoteSession(_) => Some("REMOTE_SESSION_DETECTED"),
            Self::VirtualMachine(_) => Some("VM_DETECTED"),
            Self::ClientIntegrity(_) => Some("CLIENT_INTEGRITY_WARNING"),
            Self::ProcessStarted { .. }
            | Self::ProcessExited { .. }
            | Self::ProcessWindowsChanged { .. }
            | Self::DeviceChanged(_)
            | Self::OverlayWindow(_) => None,
        }
    }

    /// When it was observed.
    pub fn at_ms(&self) -> i64 {
        match self {
            Self::ProcessStarted { at_ms, .. }
            | Self::ProcessExited { at_ms, .. }
            | Self::ProcessWindowsChanged { at_ms, .. } => *at_ms,
            Self::FocusChanged(c) => c.at_ms,
            Self::Minimize(c) => c.at_ms,
            Self::DisplayChanged(c) => c.at_ms,
            Self::DeviceChanged(c) => c.at_ms,
            Self::VirtualDevice(c) => c.at_ms,
            Self::CaptureExcludedWindow(c) | Self::OverlayWindow(c) => c.at_ms,
            Self::RemoteSession(c) => c.at_ms,
            Self::VirtualMachine(c) => c.at_ms,
            Self::ClientIntegrity(c) => c.at_ms,
        }
    }
}

/// §60's process metadata.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProcessInfo {
    pub pid: u32,
    pub parent_pid: u32,
    /// The executable's file name, as the process list shows it.
    pub name: String,
    /// The full executable path, when the process could be opened.
    pub path: Option<String>,
    /// When the process started.
    pub start_time_ms: Option<i64>,
    /// Titles of its visible top-level windows.
    pub window_titles: Vec<String>,
    /// Lower-case hex SHA-256 of the executable file.
    pub sha256: Option<String>,
    pub signature: SignatureInfo,
    /// The interview app itself or one of its descendants (WebView2): never blocked.
    pub interview_app: bool,
}

/// The Authenticode signature of an executable.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct SignatureInfo {
    pub status: SignatureStatus,
    /// Embedded in the file or found in a system catalog.
    pub kind: Option<SignatureKind>,
    /// The signer certificate's subject name (the publisher).
    pub signer: Option<String>,
    /// Lower-case hex SHA-256 of the signer certificate.
    pub signer_cert_sha256: Option<String>,
}

impl SignatureInfo {
    /// Whether the signature verified.
    pub fn is_valid(&self) -> bool {
        self.status == SignatureStatus::Valid
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SignatureStatus {
    Valid,
    Unsigned,
    /// Signed, but the signature or its chain didn't verify.
    Invalid,
    /// Not checked: no path, or the file couldn't be read.
    #[default]
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SignatureKind {
    Embedded,
    Catalog,
}

/// An application as focus tracking sees it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AppRef {
    pub pid: u32,
    /// The executable's file name.
    pub name: String,
    pub window_title: String,
    /// The interview app or one of its windows.
    pub interview_app: bool,
}

/// The foreground moved from `previous` to `new` (§62: timestamp, previous app, new app,
/// duration).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FocusChange {
    pub at_ms: i64,
    pub previous: Option<AppRef>,
    pub new: AppRef,
    /// How long `previous` held the foreground.
    pub previous_duration_ms: Option<u64>,
}

/// A window was minimised (`minimized`) or restored.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MinimizeChange {
    pub at_ms: i64,
    pub app: AppRef,
    pub minimized: bool,
}

/// A connected display.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DisplayInfo {
    /// The GDI device name (`\\.\DISPLAY1`), which identifies the display across scans.
    pub name: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub primary: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DisplayChangeKind {
    Connected,
    Disconnected,
    /// The same display with another resolution, position or primary flag.
    Reconfigured,
    /// More than one display when monitoring started.
    PresentAtStart,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DisplayChange {
    pub at_ms: i64,
    pub change: DisplayChangeKind,
    pub display: DisplayInfo,
    /// The display before a reconfiguration.
    pub previous: Option<DisplayInfo>,
    pub display_count: usize,
    pub previous_count: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceKind {
    Camera,
    Microphone,
}

/// A video or audio capture device.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize)]
pub struct CaptureDevice {
    pub kind: DeviceKind,
    /// The symbolic link (camera) or endpoint id (microphone): stable while connected.
    pub id: String,
    pub name: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceChangeKind {
    Connected,
    Disconnected,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DeviceChange {
    pub at_ms: i64,
    pub change: DeviceChangeKind,
    pub device: CaptureDevice,
    /// Devices of the same kind still connected afterwards.
    pub remaining: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct VirtualDeviceFound {
    pub at_ms: i64,
    pub device: CaptureDevice,
    /// The catalogue entry the name matched.
    pub matched: String,
    pub at_start: bool,
}

/// A window of another process.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct WindowSighting {
    pub at_ms: i64,
    pub pid: u32,
    pub process_name: String,
    pub window_title: String,
    /// `GetWindowDisplayAffinity`: `0x11` excluded from capture, `0x1` monitor-only.
    pub display_affinity: u32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RemoteSession {
    pub at_ms: i64,
    /// `SM_REMOTESESSION`: the session itself is remote (RDP).
    pub remote_session: bool,
    /// `SM_REMOTECONTROL`: the console session is being remote-controlled.
    pub remote_control: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct VirtualMachine {
    pub at_ms: i64,
    /// The CPUID hypervisor-present bit.
    pub hypervisor_present: bool,
    /// The hypervisor vendor string (`Microsoft Hv` is also seen on hosts with VBS).
    pub vendor: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct IntegrityFinding {
    pub at_ms: i64,
    /// `debugger_attached` or `webview_environment`.
    pub reason: String,
    pub detail: Option<String>,
}
