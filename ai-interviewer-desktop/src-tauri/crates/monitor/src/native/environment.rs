//! Remote sessions and the hypervisor check.

use windows::Win32::UI::WindowsAndMessaging::{
    GetSystemMetrics, SM_REMOTECONTROL, SM_REMOTESESSION,
};

/// `(remote session, remote control)`: the session is RDP, or the console is being
/// remote-controlled (shadowed).
pub(crate) fn remote() -> (bool, bool) {
    // SAFETY: GetSystemMetrics only reads a system value for a valid index.
    let session = unsafe { GetSystemMetrics(SM_REMOTESESSION) } != 0;
    // SAFETY: as above.
    let control = unsafe { GetSystemMetrics(SM_REMOTECONTROL) } != 0;
    (session, control)
}

/// The CPUID hypervisor-present bit and, when set, the hypervisor vendor string.
///
/// Evidence only: Windows hosts with virtualisation-based security also run under Hyper-V
/// (`Microsoft Hv`).
#[cfg(target_arch = "x86_64")]
pub(crate) fn hypervisor() -> (bool, Option<String>) {
    use std::arch::x86_64::__cpuid;

    // SAFETY: CPUID exists on every x86-64 processor; leaf 1 is always valid.
    #[allow(unused_unsafe)]
    let features = unsafe { __cpuid(1) };
    let present = features.ecx & (1 << 31) != 0;
    if !present {
        return (false, None);
    }
    // SAFETY: with the hypervisor bit set, leaf 0x4000_0000 is the hypervisor's vendor leaf.
    #[allow(unused_unsafe)]
    let vendor = unsafe { __cpuid(0x4000_0000) };
    let bytes: Vec<u8> = [vendor.ebx, vendor.ecx, vendor.edx]
        .iter()
        .flat_map(|r| r.to_le_bytes())
        .collect();
    let text = String::from_utf8_lossy(&bytes)
        .trim_matches(char::from(0))
        .trim()
        .to_owned();
    (true, (!text.is_empty()).then_some(text))
}

/// No CPUID on this architecture: the check can't tell.
#[cfg(not(target_arch = "x86_64"))]
pub(crate) fn hypervisor() -> (bool, Option<String>) {
    (false, None)
}
