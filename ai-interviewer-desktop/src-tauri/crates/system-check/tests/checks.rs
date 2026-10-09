//! Runs the real checks on this machine. On Windows (the CI runner and developer PCs)
//! every native check measures something; elsewhere they are all skipped.

use hv_system_check::{NATIVE_CHECKS, Status, names, native_checks, screen_capture_probe};

fn checks_of(results: &[hv_system_check::CheckResult]) -> Vec<&str> {
    results.iter().map(|result| result.check.as_str()).collect()
}

#[test]
fn native_checks_report_each_check_once_in_order() {
    let results = native_checks();
    assert_eq!(checks_of(&results), NATIVE_CHECKS);
}

#[cfg(windows)]
#[test]
fn native_checks_measure_a_value_and_explain_anything_short_of_a_pass() {
    for result in native_checks() {
        assert_ne!(result.status, Status::Skipped, "{result:?}");
        assert!(
            result
                .value
                .as_deref()
                .is_some_and(|value| !value.is_empty()),
            "no value: {result:?}"
        );
        if result.status != Status::Pass {
            assert!(
                result
                    .detail
                    .as_deref()
                    .is_some_and(|detail| !detail.is_empty()),
                "no detail: {result:?}"
            );
        }
    }
}

#[cfg(windows)]
#[test]
fn the_os_check_reads_the_windows_build() {
    let os = native_checks()
        .into_iter()
        .find(|result| result.check == names::OS)
        .expect("an os result");
    let value = os.value.expect("an os value");
    assert!(value.starts_with("Windows 1"), "{value}");
    let build: u32 = value
        .split_whitespace()
        .nth(2)
        .and_then(|version| version.split('.').next())
        .and_then(|build| build.parse().ok())
        .expect("a build number");
    assert!(build >= 10_240, "{value}");
}

#[cfg(windows)]
#[test]
fn the_screen_capture_probe_passes_or_says_why() {
    let result = screen_capture_probe();
    assert_eq!(result.check, names::SCREEN_CAPTURE);
    match result.status {
        Status::Pass => {
            let value = result.value.expect("a display count");
            assert!(
                value.ends_with("display") || value.ends_with("displays"),
                "{value}"
            );
        }
        Status::Fail => assert!(
            result
                .detail
                .as_deref()
                .is_some_and(|detail| !detail.is_empty()),
            "a failure needs a detail: {result:?}"
        ),
        other => panic!("unexpected status {other:?}: {result:?}"),
    }
}

#[cfg(not(windows))]
#[test]
fn everything_is_skipped_off_windows() {
    for result in native_checks() {
        assert_eq!(result.status, Status::Skipped, "{result:?}");
    }
    assert_eq!(screen_capture_probe().status, Status::Skipped);
    assert_eq!(screen_capture_probe().check, names::SCREEN_CAPTURE);
}

/// Windows Graphics Capture closes sessions on its own threads after the probe returns.
/// Tearing COM down under them crashed the process a moment later, so stay alive a while.
#[cfg(windows)]
#[test]
fn the_process_outlives_the_screen_capture_probe() {
    let first = screen_capture_probe();
    std::thread::sleep(std::time::Duration::from_millis(1_500));
    let second = screen_capture_probe();
    std::thread::sleep(std::time::Duration::from_millis(1_500));
    assert_eq!(first.status, second.status, "{first:?} then {second:?}");
}
