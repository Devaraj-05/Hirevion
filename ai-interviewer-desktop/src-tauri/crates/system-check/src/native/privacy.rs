//! The Windows camera and microphone privacy settings (Settings > Privacy & security).

use super::registry::read_string;
use crate::classify::{Consent, classify_privacy, consent_from_values};
use crate::result::CheckResult;
use windows::Win32::System::Registry::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};

const CONSENT_STORE: &str =
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore";

pub(super) fn check() -> CheckResult {
    classify_privacy(consent("webcam"), consent("microphone"))
}

/// Combines the device-wide switch (HKLM), the user's "let apps access" switch (HKCU) and
/// the "let desktop apps access" switch (the `NonPackaged` subkeys).
fn consent(capability: &str) -> Consent {
    let key = format!(r"{CONSENT_STORE}\{capability}");
    let desktop_apps = format!(r"{key}\NonPackaged");
    let mut values = Vec::new();
    for root in [HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER] {
        for subkey in [&key, &desktop_apps] {
            values.push(read_string(root, subkey, "Value"));
        }
    }
    consent_from_values(values.iter().map(Option::as_deref))
}
