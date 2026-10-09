//! The thresholds of the SP-08a plan as pure functions, so every boundary is unit-tested
//! on any platform. The Windows code only measures and hands the numbers to these.

use crate::result::{CheckResult, Status, names};
use std::time::Duration;

pub const GIB: u64 = 1 << 30;

pub const CPU_MIN_LOGICAL: u32 = 4;
/// Busy percentages from here up warn.
pub const CPU_BUSY_WARN_PERCENT: u32 = 80;
pub const MEMORY_PASS_BYTES: u64 = 2 * GIB;
pub const MEMORY_WARN_BYTES: u64 = GIB;
pub const DISK_PASS_BYTES: u64 = 5 * GIB;
pub const DISK_WARN_BYTES: u64 = 2 * GIB;
/// Windows 11's first build.
pub const OS_RECOMMENDED_BUILD: u32 = 22_000;
/// Windows 10 2004, the first with cursor control in Windows Graphics Capture.
pub const OS_MIN_BUILD: u32 = 19_041;

pub const PRIVACY_CAMERA_SETTINGS: &str = "ms-settings:privacy-webcam";
pub const PRIVACY_MICROPHONE_SETTINGS: &str = "ms-settings:privacy-microphone";

/// Cumulative processor times from `GetSystemTimes`, in 100 ns units. `kernel` includes idle.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CpuTimes {
    pub idle: u64,
    pub kernel: u64,
    pub user: u64,
}

/// The share of the interval the processors weren't idle, rounded to a whole percent
/// (0–100). Counters that went backwards count as no time passing.
#[must_use]
pub fn busy_percent(before: CpuTimes, after: CpuTimes) -> u32 {
    let idle = u128::from(after.idle.saturating_sub(before.idle));
    let total = u128::from(after.kernel.saturating_sub(before.kernel))
        + u128::from(after.user.saturating_sub(before.user));
    if total == 0 {
        return 0;
    }
    let busy = total.saturating_sub(idle);
    let percent = (busy * 100 + total / 2) / total;
    u32::try_from(percent.min(100)).unwrap_or(100)
}

/// Passes with at least 4 logical processors under 80% busy; anything less only warns,
/// since the interview still runs, more slowly.
#[must_use]
pub fn classify_cpu(logical: u32, busy_percent: u32) -> CheckResult {
    let value = format!("{logical} logical, {busy_percent}% busy");
    let mut problems = Vec::new();
    if logical < CPU_MIN_LOGICAL {
        problems.push(format!(
            "This computer has fewer than {CPU_MIN_LOGICAL} logical processors, so the interview may run slowly."
        ));
    }
    if busy_percent >= CPU_BUSY_WARN_PERCENT {
        problems.push(format!(
            "The processor is {busy_percent}% busy. Close other apps before you start."
        ));
    }
    let result = CheckResult::new(names::CPU, Status::Pass).with_value(value);
    if problems.is_empty() {
        result
    } else {
        CheckResult {
            status: Status::Warn,
            ..result.with_detail(problems.join(" "))
        }
    }
}

/// At least 2 GB free passes, at least 1 GB warns, less fails.
#[must_use]
pub fn classify_memory(free_bytes: u64) -> CheckResult {
    let result = CheckResult::new(names::MEMORY, Status::Pass)
        .with_value(format!("{} free", format_gb(free_bytes)));
    if free_bytes >= MEMORY_PASS_BYTES {
        result
    } else if free_bytes >= MEMORY_WARN_BYTES {
        CheckResult {
            status: Status::Warn,
            ..result
                .with_detail("Less than 2 GB of memory is free. Close other apps before you start.")
        }
    } else {
        CheckResult {
            status: Status::Fail,
            ..result.with_detail(
                "Less than 1 GB of memory is free. Close other apps, then check again.",
            )
        }
    }
}

/// At least 5 GB free passes, at least 2 GB warns, less fails.
#[must_use]
pub fn classify_disk(free_bytes: u64) -> CheckResult {
    let result = CheckResult::new(names::DISK, Status::Pass)
        .with_value(format!("{} free", format_gb(free_bytes)));
    if free_bytes >= DISK_PASS_BYTES {
        result
    } else if free_bytes >= DISK_WARN_BYTES {
        CheckResult {
            status: Status::Warn,
            ..result.with_detail(
                "Less than 5 GB of disk space is free. The interview recording may run out of room.",
            )
        }
    } else {
        CheckResult {
            status: Status::Fail,
            ..result.with_detail(
                "Less than 2 GB of disk space is free. Free up space for the interview recording, then check again.",
            )
        }
    }
}

/// One display passes. More warn, or fail when the interview allows a single display.
#[must_use]
pub fn classify_displays(count: usize, single_display_policy: bool) -> CheckResult {
    let result = CheckResult::new(names::DISPLAYS, Status::Pass).with_value(count.to_string());
    match count {
        0 => CheckResult {
            status: Status::Fail,
            ..result.with_detail("No display was found.")
        },
        1 => result,
        _ if single_display_policy => CheckResult {
            status: Status::Fail,
            ..result.with_detail(format!(
                "{count} displays are connected, and this interview allows only one. Disconnect the others, then check again."
            ))
        },
        _ => CheckResult {
            status: Status::Warn,
            ..result.with_detail(format!(
                "{count} displays are connected. Use a single display if you can."
            ))
        },
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Consent {
    Allowed,
    Denied,
}

/// Combines the `Value` entries of every consent-store layer (device, user, desktop apps):
/// a `Deny` in any of them blocks the device. Missing entries mean Windows' default, allow.
#[must_use]
pub fn consent_from_values<'a>(values: impl IntoIterator<Item = Option<&'a str>>) -> Consent {
    let denied = values
        .into_iter()
        .flatten()
        .any(|value| value.trim().eq_ignore_ascii_case("deny"));
    if denied {
        Consent::Denied
    } else {
        Consent::Allowed
    }
}

/// Passes when Windows lets desktop apps use both the camera and the microphone. Each
/// blocked device's detail names its Settings page, which the app can open.
#[must_use]
pub fn classify_privacy(camera: Consent, microphone: Consent) -> CheckResult {
    let mut blocked = Vec::new();
    let mut details = Vec::new();
    if camera == Consent::Denied {
        blocked.push("camera");
        details.push(format!(
            "Windows privacy settings block the camera. Turn on camera access for desktop apps in Settings ({PRIVACY_CAMERA_SETTINGS})."
        ));
    }
    if microphone == Consent::Denied {
        blocked.push("microphone");
        details.push(format!(
            "Windows privacy settings block the microphone. Turn on microphone access for desktop apps in Settings ({PRIVACY_MICROPHONE_SETTINGS})."
        ));
    }
    if blocked.is_empty() {
        return CheckResult::new(names::PRIVACY, Status::Pass)
            .with_value("camera and microphone allowed");
    }
    CheckResult::new(names::PRIVACY, Status::Fail)
        .with_value(format!("{} blocked", blocked.join(" and ")))
        .with_detail(details.join(" "))
}

/// What the Media Foundation probe found.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MediaFoundationProbe {
    /// `mfplat.dll` isn't installed (Windows N editions without the Media Feature Pack).
    Missing,
    /// Media Foundation is installed but didn't start or enumerate.
    Failed(String),
    /// The H.264 video encoders found.
    Encoders { hardware: usize, software: usize },
}

const MEDIA_FEATURE_PACK: &str = "On Windows N editions, add the Media Feature Pack in Settings > System > Optional features, then restart the computer.";

/// Passes with any H.264 encoder, which recording needs; fails otherwise.
#[must_use]
pub fn classify_media_foundation(probe: &MediaFoundationProbe) -> CheckResult {
    let fail = CheckResult::new(names::MEDIA_FOUNDATION, Status::Fail);
    match probe {
        MediaFoundationProbe::Missing => fail
            .with_value("Media Foundation missing")
            .with_detail(format!(
                "Windows Media Foundation, which records the interview, is not installed. {MEDIA_FEATURE_PACK}"
            )),
        MediaFoundationProbe::Failed(error) => fail
            .with_value("Media Foundation unavailable")
            .with_detail(format!("Windows Media Foundation did not start: {error}")),
        MediaFoundationProbe::Encoders {
            hardware: 0,
            software: 0,
        } => fail.with_value("no H.264 encoder").with_detail(format!(
            "Windows has no H.264 video encoder to record the interview. {MEDIA_FEATURE_PACK}"
        )),
        MediaFoundationProbe::Encoders { hardware, .. } => {
            let kind = if *hardware > 0 { "hardware" } else { "software" };
            CheckResult::new(names::MEDIA_FOUNDATION, Status::Pass)
                .with_value(format!("H.264 encoder present ({kind})"))
        }
    }
}

/// "Windows 11 26200.6899" from the build and update revision. Windows 11 still calls
/// itself Windows 10 in the registry's `ProductName`, so the build decides.
#[must_use]
pub fn os_label(build: u32, ubr: Option<u32>) -> String {
    let name = if build >= OS_RECOMMENDED_BUILD {
        "Windows 11"
    } else {
        "Windows 10"
    };
    match ubr {
        Some(ubr) => format!("{name} {build}.{ubr}"),
        None => format!("{name} {build}"),
    }
}

/// Windows 11 passes, Windows 10 2004 or later warns, anything older fails.
#[must_use]
pub fn classify_os(build: u32, ubr: Option<u32>) -> CheckResult {
    let result = CheckResult::new(names::OS, Status::Pass).with_value(os_label(build, ubr));
    if build >= OS_RECOMMENDED_BUILD {
        result
    } else if build >= OS_MIN_BUILD {
        CheckResult {
            status: Status::Warn,
            ..result.with_detail(
                "Windows 10 no longer gets regular security updates. Update to Windows 11 when you can.",
            )
        }
    } else {
        CheckResult {
            status: Status::Fail,
            ..result.with_detail(format!(
                "Windows 10 version 2004 (build {OS_MIN_BUILD}) or later is needed. Update Windows, then check again."
            ))
        }
    }
}

/// What capturing one display produced.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FrameOutcome {
    Frame,
    /// Capture started but no frame arrived in time.
    NoFrame,
    /// Capture couldn't start or failed.
    Error(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MonitorProbe {
    /// The display's device name, such as `\\.\DISPLAY1`.
    pub name: String,
    pub outcome: FrameOutcome,
}

/// Passes when every display gave a frame; otherwise names each display that didn't.
#[must_use]
pub fn classify_screen_capture(monitors: &[MonitorProbe], timeout: Duration) -> CheckResult {
    let fail = CheckResult::new(names::SCREEN_CAPTURE, Status::Fail);
    if monitors.is_empty() {
        return fail
            .with_value("no display")
            .with_detail("No display was found to capture.");
    }
    let total = monitors.len();
    let failures: Vec<String> = monitors
        .iter()
        .filter_map(|monitor| match &monitor.outcome {
            FrameOutcome::Frame => None,
            FrameOutcome::NoFrame => Some(format!(
                "{}: no frame within {}",
                monitor.name,
                format_duration(timeout)
            )),
            FrameOutcome::Error(error) => Some(format!("{}: {error}", monitor.name)),
        })
        .collect();
    if failures.is_empty() {
        let plural = if total == 1 { "" } else { "s" };
        return CheckResult::new(names::SCREEN_CAPTURE, Status::Pass)
            .with_value(format!("{total} display{plural}"));
    }
    fail.with_value(format!("{} of {total} displays", total - failures.len()))
        .with_detail(format!(
            "The screen could not be captured ({}).",
            failures.join("; ")
        ))
}

/// Whole gigabytes (2^30 bytes) at 10 GB and above, tenths below, always rounded down so a
/// value under a threshold never prints as the threshold.
#[must_use]
pub fn format_gb(bytes: u64) -> String {
    let tenths = u128::from(bytes) * 10 / u128::from(GIB);
    if tenths < 100 {
        format!("{}.{} GB", tenths / 10, tenths % 10)
    } else {
        format!("{} GB", tenths / 10)
    }
}

fn format_duration(duration: Duration) -> String {
    if duration.subsec_millis() == 0 {
        format!("{} s", duration.as_secs())
    } else {
        format!("{} ms", duration.as_millis())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn status(result: &CheckResult) -> Status {
        result.status
    }

    #[test]
    fn busy_percent_is_the_non_idle_share_of_the_interval() {
        let before = CpuTimes {
            idle: 1_000,
            kernel: 2_000,
            user: 1_000,
        };
        // 1 000 units elapsed: 750 idle (inside kernel), 250 busy.
        let after = CpuTimes {
            idle: 1_750,
            kernel: 2_800,
            user: 1_200,
        };
        assert_eq!(busy_percent(before, after), 25);
    }

    #[test]
    fn busy_percent_is_zero_when_no_time_passed() {
        let times = CpuTimes {
            idle: 5,
            kernel: 10,
            user: 3,
        };
        assert_eq!(busy_percent(times, times), 0);
    }

    #[test]
    fn busy_percent_stays_in_range_when_counters_go_backwards() {
        let before = CpuTimes {
            idle: 100,
            kernel: 100,
            user: 100,
        };
        assert_eq!(busy_percent(before, CpuTimes::default()), 0);
        let all_busy = CpuTimes {
            idle: 100,
            kernel: 200,
            user: 200,
        };
        assert_eq!(busy_percent(before, all_busy), 100);
    }

    #[test]
    fn cpu_passes_with_four_cores_under_eighty_percent() {
        let result = classify_cpu(4, 79);
        assert_eq!(result.check, names::CPU);
        assert_eq!(status(&result), Status::Pass);
        assert_eq!(result.value.as_deref(), Some("4 logical, 79% busy"));
        assert_eq!(result.detail, None);
    }

    #[test]
    fn cpu_warns_at_eighty_percent_busy() {
        let result = classify_cpu(8, 80);
        assert_eq!(status(&result), Status::Warn);
        assert!(result.detail.unwrap().contains("80%"));
    }

    #[test]
    fn cpu_warns_below_four_cores() {
        let result = classify_cpu(3, 10);
        assert_eq!(status(&result), Status::Warn);
        assert_eq!(result.value.as_deref(), Some("3 logical, 10% busy"));
        assert!(result.detail.unwrap().contains("4 logical"));
    }

    #[test]
    fn memory_thresholds() {
        assert_eq!(status(&classify_memory(MEMORY_PASS_BYTES)), Status::Pass);
        assert_eq!(
            status(&classify_memory(MEMORY_PASS_BYTES - 1)),
            Status::Warn
        );
        assert_eq!(status(&classify_memory(MEMORY_WARN_BYTES)), Status::Warn);
        assert_eq!(
            status(&classify_memory(MEMORY_WARN_BYTES - 1)),
            Status::Fail
        );
        assert_eq!(status(&classify_memory(0)), Status::Fail);
    }

    #[test]
    fn memory_reports_free_gigabytes() {
        let result = classify_memory(6 * GIB + GIB / 10 + 1);
        assert_eq!(result.check, names::MEMORY);
        assert_eq!(result.value.as_deref(), Some("6.1 GB free"));
        assert_eq!(result.detail, None);
        assert!(classify_memory(GIB).detail.is_some());
        assert!(classify_memory(0).detail.is_some());
    }

    #[test]
    fn disk_thresholds() {
        assert_eq!(status(&classify_disk(DISK_PASS_BYTES)), Status::Pass);
        assert_eq!(status(&classify_disk(DISK_PASS_BYTES - 1)), Status::Warn);
        assert_eq!(status(&classify_disk(DISK_WARN_BYTES)), Status::Warn);
        assert_eq!(status(&classify_disk(DISK_WARN_BYTES - 1)), Status::Fail);
    }

    #[test]
    fn disk_reports_free_gigabytes() {
        let result = classify_disk(41 * GIB + GIB / 2);
        assert_eq!(result.check, names::DISK);
        assert_eq!(result.value.as_deref(), Some("41 GB free"));
        assert!(classify_disk(DISK_WARN_BYTES).detail.is_some());
    }

    #[test]
    fn gigabytes_round_down_so_a_warning_never_shows_the_threshold() {
        assert_eq!(format_gb(2 * GIB - 1), "1.9 GB");
        assert_eq!(format_gb(2 * GIB), "2.0 GB");
        assert_eq!(format_gb(10 * GIB - 1), "9.9 GB");
        assert_eq!(format_gb(10 * GIB), "10 GB");
        assert_eq!(format_gb(0), "0.0 GB");
        assert_eq!(format_gb(u64::MAX), "17179869183 GB");
    }

    #[test]
    fn one_display_passes() {
        let result = classify_displays(1, false);
        assert_eq!(result.check, names::DISPLAYS);
        assert_eq!(status(&result), Status::Pass);
        assert_eq!(result.value.as_deref(), Some("1"));
    }

    #[test]
    fn extra_displays_warn_or_fail_under_a_single_display_policy() {
        let warned = classify_displays(2, false);
        assert_eq!(status(&warned), Status::Warn);
        assert_eq!(warned.value.as_deref(), Some("2"));
        assert!(warned.detail.is_some());
        assert_eq!(status(&classify_displays(3, true)), Status::Fail);
        assert_eq!(status(&classify_displays(1, true)), Status::Pass);
    }

    #[test]
    fn no_display_fails() {
        let result = classify_displays(0, false);
        assert_eq!(status(&result), Status::Fail);
        assert_eq!(result.value.as_deref(), Some("0"));
    }

    #[test]
    fn consent_is_denied_when_any_layer_denies() {
        assert_eq!(
            consent_from_values([Some("Allow"), None, Some("Allow")]),
            Consent::Allowed
        );
        assert_eq!(consent_from_values([None, None]), Consent::Allowed);
        assert_eq!(
            consent_from_values([Some("Allow"), Some("Deny")]),
            Consent::Denied
        );
        assert_eq!(consent_from_values([Some("deny")]), Consent::Denied);
        assert_eq!(consent_from_values([Some("Prompt")]), Consent::Allowed);
    }

    #[test]
    fn privacy_passes_when_both_are_allowed() {
        let result = classify_privacy(Consent::Allowed, Consent::Allowed);
        assert_eq!(result.check, names::PRIVACY);
        assert_eq!(status(&result), Status::Pass);
        assert_eq!(
            result.value.as_deref(),
            Some("camera and microphone allowed")
        );
        assert_eq!(result.detail, None);
    }

    #[test]
    fn privacy_names_the_settings_page_of_each_blocked_device() {
        let camera = classify_privacy(Consent::Denied, Consent::Allowed);
        assert_eq!(status(&camera), Status::Fail);
        assert_eq!(camera.value.as_deref(), Some("camera blocked"));
        let detail = camera.detail.unwrap();
        assert!(detail.contains(PRIVACY_CAMERA_SETTINGS));
        assert!(!detail.contains(PRIVACY_MICROPHONE_SETTINGS));

        let microphone = classify_privacy(Consent::Allowed, Consent::Denied);
        assert_eq!(microphone.value.as_deref(), Some("microphone blocked"));
        assert!(
            microphone
                .detail
                .unwrap()
                .contains(PRIVACY_MICROPHONE_SETTINGS)
        );

        let both = classify_privacy(Consent::Denied, Consent::Denied);
        assert_eq!(both.value.as_deref(), Some("camera and microphone blocked"));
        let detail = both.detail.unwrap();
        assert!(detail.contains(PRIVACY_CAMERA_SETTINGS));
        assert!(detail.contains(PRIVACY_MICROPHONE_SETTINGS));
    }

    #[test]
    fn media_foundation_passes_with_any_h264_encoder() {
        let hardware = classify_media_foundation(&MediaFoundationProbe::Encoders {
            hardware: 1,
            software: 1,
        });
        assert_eq!(hardware.check, names::MEDIA_FOUNDATION);
        assert_eq!(status(&hardware), Status::Pass);
        assert_eq!(
            hardware.value.as_deref(),
            Some("H.264 encoder present (hardware)")
        );
        let software = classify_media_foundation(&MediaFoundationProbe::Encoders {
            hardware: 0,
            software: 1,
        });
        assert_eq!(status(&software), Status::Pass);
        assert_eq!(
            software.value.as_deref(),
            Some("H.264 encoder present (software)")
        );
    }

    #[test]
    fn media_foundation_fails_without_an_encoder_and_points_to_the_feature_pack() {
        for probe in [
            MediaFoundationProbe::Missing,
            MediaFoundationProbe::Encoders {
                hardware: 0,
                software: 0,
            },
        ] {
            let result = classify_media_foundation(&probe);
            assert_eq!(status(&result), Status::Fail, "{probe:?}");
            assert!(result.value.is_some());
            assert!(result.detail.unwrap().contains("Media Feature Pack"));
        }
    }

    #[test]
    fn media_foundation_reports_a_startup_error() {
        let result = classify_media_foundation(&MediaFoundationProbe::Failed("boom".into()));
        assert_eq!(status(&result), Status::Fail);
        assert!(result.detail.unwrap().contains("boom"));
    }

    #[test]
    fn os_label_names_windows_11_from_its_build() {
        assert_eq!(os_label(26_200, Some(6_899)), "Windows 11 26200.6899");
        assert_eq!(os_label(22_000, None), "Windows 11 22000");
        assert_eq!(os_label(19_045, Some(5_371)), "Windows 10 19045.5371");
    }

    #[test]
    fn os_thresholds() {
        let current = classify_os(OS_RECOMMENDED_BUILD, Some(1));
        assert_eq!(current.check, names::OS);
        assert_eq!(status(&current), Status::Pass);
        assert_eq!(current.value.as_deref(), Some("Windows 11 22000.1"));
        assert_eq!(
            status(&classify_os(OS_RECOMMENDED_BUILD - 1, None)),
            Status::Warn
        );
        assert_eq!(status(&classify_os(OS_MIN_BUILD, None)), Status::Warn);
        let old = classify_os(OS_MIN_BUILD - 1, None);
        assert_eq!(status(&old), Status::Fail);
        assert!(old.detail.unwrap().contains("19041"));
    }

    fn probe(name: &str, outcome: FrameOutcome) -> MonitorProbe {
        MonitorProbe {
            name: name.into(),
            outcome,
        }
    }

    #[test]
    fn screen_capture_passes_when_every_display_gives_a_frame() {
        let timeout = Duration::from_secs(2);
        let one = classify_screen_capture(&[probe("A", FrameOutcome::Frame)], timeout);
        assert_eq!(one.check, names::SCREEN_CAPTURE);
        assert_eq!(status(&one), Status::Pass);
        assert_eq!(one.value.as_deref(), Some("1 display"));
        let two = classify_screen_capture(
            &[
                probe("A", FrameOutcome::Frame),
                probe("B", FrameOutcome::Frame),
            ],
            timeout,
        );
        assert_eq!(two.value.as_deref(), Some("2 displays"));
    }

    #[test]
    fn screen_capture_names_the_displays_that_failed() {
        let result = classify_screen_capture(
            &[
                probe("A", FrameOutcome::Frame),
                probe("B", FrameOutcome::NoFrame),
                probe("C", FrameOutcome::Error("access denied".into())),
            ],
            Duration::from_secs(2),
        );
        assert_eq!(status(&result), Status::Fail);
        assert_eq!(result.value.as_deref(), Some("1 of 3 displays"));
        let detail = result.detail.unwrap();
        assert!(detail.contains("B: no frame within 2 s"), "{detail}");
        assert!(detail.contains("C: access denied"), "{detail}");
        assert!(!detail.contains("A:"), "{detail}");
    }

    #[test]
    fn screen_capture_fails_without_displays() {
        let result = classify_screen_capture(&[], Duration::from_secs(2));
        assert_eq!(status(&result), Status::Fail);
        assert!(result.value.is_some());
        assert!(result.detail.is_some());
    }
}
