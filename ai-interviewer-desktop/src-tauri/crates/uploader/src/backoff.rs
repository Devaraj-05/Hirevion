//! Retry timing: exponential backoff with jitter, capped at 30 s (contracts README).

use std::time::Duration;

use rand_core::{OsRng, RngCore as _};

/// The first retry waits about this long.
pub const DEFAULT_BASE: Duration = Duration::from_millis(500);
/// No retry waits longer than this, unless the server's `Retry-After` says so.
pub const DEFAULT_CAP: Duration = Duration::from_secs(30);
/// A `Retry-After` longer than this is treated as this.
pub const MAX_RETRY_AFTER: Duration = Duration::from_secs(300);

/// The wait before retry number `attempt` (0 for the first retry): `base × 2^attempt`, capped,
/// with "equal jitter": half of it fixed and half scaled by `jitter` (0.0–1.0), so clients that
/// failed together spread out but never retry immediately.
#[must_use]
pub fn backoff(attempt: u32, base: Duration, cap: Duration, jitter: f64) -> Duration {
    let ceiling = base
        .checked_mul(1u32.checked_shl(attempt.min(31)).unwrap_or(u32::MAX))
        .unwrap_or(cap)
        .min(cap);
    ceiling / 2 + ceiling.mul_f64(jitter.clamp(0.0, 1.0) / 2.0)
}

/// The wait before a retry: the server's `Retry-After` (seconds) when it sent one, but never
/// less than the backoff.
#[must_use]
pub fn retry_delay(
    retry_after: Option<u64>,
    attempt: u32,
    base: Duration,
    cap: Duration,
    jitter: f64,
) -> Duration {
    let backoff = backoff(attempt, base, cap, jitter);
    retry_after.map_or(backoff, |seconds| {
        Duration::from_secs(seconds)
            .min(MAX_RETRY_AFTER)
            .max(backoff)
    })
}

/// A random jitter factor in 0.0–1.0.
#[must_use]
pub fn jitter() -> f64 {
    f64::from(OsRng.next_u32()) / f64::from(u32::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ms(value: u64) -> Duration {
        Duration::from_millis(value)
    }

    #[test]
    fn doubles_from_the_base_up_to_the_cap() {
        let full: Vec<Duration> = (0..9)
            .map(|attempt| backoff(attempt, DEFAULT_BASE, DEFAULT_CAP, 1.0))
            .collect();
        assert_eq!(
            full,
            [
                ms(500),
                ms(1_000),
                ms(2_000),
                ms(4_000),
                ms(8_000),
                ms(16_000),
                ms(30_000),
                ms(30_000),
                ms(30_000)
            ]
        );
    }

    #[test]
    fn jitter_spreads_between_half_and_the_full_delay() {
        assert_eq!(backoff(3, DEFAULT_BASE, DEFAULT_CAP, 0.0), ms(2_000));
        assert_eq!(backoff(3, DEFAULT_BASE, DEFAULT_CAP, 0.5), ms(3_000));
        assert_eq!(backoff(3, DEFAULT_BASE, DEFAULT_CAP, 1.0), ms(4_000));
        // Out-of-range jitter is clamped.
        assert_eq!(backoff(3, DEFAULT_BASE, DEFAULT_CAP, 7.0), ms(4_000));
    }

    #[test]
    fn never_exceeds_the_cap_even_after_many_attempts() {
        for attempt in [10, 31, 32, 1_000, u32::MAX] {
            assert!(backoff(attempt, DEFAULT_BASE, DEFAULT_CAP, 1.0) <= DEFAULT_CAP);
            assert!(backoff(attempt, DEFAULT_BASE, DEFAULT_CAP, 0.0) >= DEFAULT_CAP / 2);
        }
    }

    #[test]
    fn retry_after_wins_when_longer_but_is_bounded() {
        assert_eq!(
            retry_delay(Some(20), 0, DEFAULT_BASE, DEFAULT_CAP, 1.0),
            Duration::from_secs(20)
        );
        assert_eq!(
            retry_delay(Some(0), 4, DEFAULT_BASE, DEFAULT_CAP, 1.0),
            ms(8_000)
        );
        assert_eq!(
            retry_delay(Some(86_400), 0, DEFAULT_BASE, DEFAULT_CAP, 1.0),
            MAX_RETRY_AFTER
        );
        assert_eq!(
            retry_delay(None, 1, DEFAULT_BASE, DEFAULT_CAP, 1.0),
            ms(1_000)
        );
    }

    #[test]
    fn jitter_is_a_fraction() {
        for _ in 0..100 {
            assert!((0.0..=1.0).contains(&jitter()));
        }
    }
}
