//! Measurement helpers for the capture benchmark.

use std::time::Duration;

/// CPU use as a percentage of all logical processors: `cpu_ticks` is CPU time in 100 ns
/// units (as reported by `GetProcessTimes`) spent during `wall` elapsed time.
#[must_use]
pub fn cpu_percent(cpu_ticks: u64, wall: Duration, logical_cpus: u32) -> f64 {
    let capacity = wall.as_secs_f64() * f64::from(logical_cpus.max(1));
    if capacity == 0.0 {
        return 0.0;
    }
    #[allow(clippy::cast_precision_loss)] // CPU ticks stay far below 2^52.
    let cpu_seconds = cpu_ticks as f64 / 10_000_000.0;
    cpu_seconds / capacity * 100.0
}

/// The `pct` percentile (0–100) with linear interpolation; `None` for an empty input.
#[must_use]
pub fn percentile(values: &[f64], pct: f64) -> Option<f64> {
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    let last = sorted.len().checked_sub(1)?;
    #[allow(clippy::cast_precision_loss)] // Sample counts are small.
    let rank = last as f64 * pct.clamp(0.0, 100.0) / 100.0;
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // 0 <= rank <= last.
    let (low, high) = (rank.floor() as usize, rank.ceil() as usize);
    let fraction = rank - rank.floor();
    Some(sorted[low] + (sorted[high] - sorted[low]) * fraction)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cpu_percent_is_relative_to_all_logical_processors() {
        let percent = cpu_percent(80_000_000, Duration::from_secs(10), 8);
        assert!((percent - 10.0).abs() < 1e-9);
    }

    #[test]
    fn cpu_percent_of_no_time_is_zero() {
        assert_eq!(cpu_percent(5, Duration::ZERO, 8), 0.0);
    }

    #[test]
    fn percentile_interpolates_linearly() {
        assert_eq!(percentile(&[4.0, 1.0, 3.0, 2.0], 50.0), Some(2.5));
        assert_eq!(percentile(&[5.0], 95.0), Some(5.0));
        let hundred: Vec<f64> = (1..=100).map(f64::from).collect();
        let p95 = percentile(&hundred, 95.0).expect("non-empty");
        assert!((p95 - 95.05).abs() < 1e-9);
    }

    #[test]
    fn percentile_of_nothing_is_none() {
        assert_eq!(percentile(&[], 50.0), None);
    }
}
