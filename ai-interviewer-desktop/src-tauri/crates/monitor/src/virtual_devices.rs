//! The catalogue of virtual camera and microphone names.

/// Name fragments of well-known virtual cameras and virtual audio cables. Matching ignores
/// case. The list is data: the app may replace it (from the session policy, later).
pub const DEFAULT_VIRTUAL_DEVICE_NAMES: &[&str] = &[
    "OBS Virtual Camera",
    "OBS-Camera",
    "OBS Virtual Audio",
    "ManyCam",
    "XSplit",
    "Snap Camera",
    "Logi Capture",
    "NVIDIA Broadcast",
    "Camo",
    "e2eSoft",
    "SplitCam",
    "YouCam",
    "CyberLink Webcam Splitter",
    "DroidCam",
    "iVCam",
    "EpocCam",
    "NDI Webcam",
    "Virtual Camera",
    "VB-Audio",
    "VB-Cable",
    "CABLE Output",
    "CABLE Input",
    "Voicemeeter",
    "Virtual Audio Cable",
    "Line 1 (Virtual Audio Cable)",
    "Krisp",
    "Voicemod",
];

/// Matches device names against virtual-device name fragments.
#[derive(Debug, Clone)]
pub struct VirtualDeviceCatalogue {
    /// The original fragments and their lower-case forms.
    names: Vec<(String, String)>,
}

impl Default for VirtualDeviceCatalogue {
    fn default() -> Self {
        Self::new(DEFAULT_VIRTUAL_DEVICE_NAMES.iter().copied())
    }
}

impl VirtualDeviceCatalogue {
    pub fn new<S: AsRef<str>>(names: impl IntoIterator<Item = S>) -> Self {
        Self {
            names: names
                .into_iter()
                .map(|n| n.as_ref().trim().to_owned())
                .filter(|n| !n.is_empty())
                .map(|n| {
                    let lower = n.to_lowercase();
                    (n, lower)
                })
                .collect(),
        }
    }

    /// The catalogue entry `device_name` contains, if any.
    pub fn matches(&self, device_name: &str) -> Option<&str> {
        let name = device_name.to_lowercase();
        self.names
            .iter()
            .find(|(_, lower)| name.contains(lower.as_str()))
            .map(|(original, _)| original.as_str())
    }
}
