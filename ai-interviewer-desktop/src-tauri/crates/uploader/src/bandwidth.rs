//! Upload throttling: a token bucket that the caller can tighten while live audio and video
//! need the link (master plan §6.11: "throttled to give way to live media").

use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

/// The smallest burst, so tiny caps still move whole chunks without stalling.
const MIN_BURST: u64 = 16 * 1024;

/// Bytes per second with a quarter-second burst. Sending more than the bucket holds goes
/// into debt: the caller waits until the debt is paid, so the average never exceeds the rate.
#[derive(Debug, Clone)]
pub struct TokenBucket {
    rate: Option<u64>,
    tokens: f64,
    last: Option<Instant>,
}

impl TokenBucket {
    /// A bucket for `rate` bytes per second (`None` is unlimited), starting full.
    #[must_use]
    pub fn new(rate: Option<u64>) -> Self {
        let rate = rate.filter(|&r| r > 0);
        Self {
            rate,
            tokens: rate.map_or(0.0, burst),
            last: None,
        }
    }

    #[must_use]
    pub fn rate(&self) -> Option<u64> {
        self.rate
    }

    /// Changes the cap from `now` on; bytes already sent keep the old rate's accounting.
    pub fn set_rate(&mut self, rate: Option<u64>, now: Instant) {
        self.refill(now);
        let rate = rate.filter(|&r| r > 0);
        match (self.rate, rate) {
            (None, Some(new)) => self.tokens = burst(new),
            (_, Some(new)) => self.tokens = self.tokens.min(burst(new)),
            (_, None) => self.tokens = 0.0,
        }
        self.rate = rate;
    }

    /// Takes `bytes` from the bucket and returns how long to wait before sending them.
    pub fn reserve(&mut self, bytes: usize, now: Instant) -> Duration {
        let Some(rate) = self.rate else {
            return Duration::ZERO;
        };
        self.refill(now);
        #[allow(clippy::cast_precision_loss)] // Chunk sizes are far below 2^52.
        let bytes = bytes as f64;
        self.tokens -= bytes;
        if self.tokens >= 0.0 {
            Duration::ZERO
        } else {
            #[allow(clippy::cast_precision_loss)] // Rates are far below 2^52.
            Duration::from_secs_f64(-self.tokens / rate as f64)
        }
    }

    fn refill(&mut self, now: Instant) {
        if let (Some(rate), Some(last)) = (self.rate, self.last) {
            let elapsed = now.saturating_duration_since(last).as_secs_f64();
            #[allow(clippy::cast_precision_loss)] // Rates are far below 2^52.
            let earned = elapsed * rate as f64;
            self.tokens = (self.tokens + earned).min(burst(rate));
        }
        self.last = Some(now);
    }
}

#[allow(clippy::cast_precision_loss)] // Rates are far below 2^52.
fn burst(rate: u64) -> f64 {
    (rate / 4).max(MIN_BURST) as f64
}

/// A shared bandwidth cap: clone it to hand the same cap to the uploader and to whatever
/// watches live media.
#[derive(Debug, Clone)]
pub struct Bandwidth(Arc<Mutex<TokenBucket>>);

impl Default for Bandwidth {
    fn default() -> Self {
        Self::unlimited()
    }
}

impl Bandwidth {
    #[must_use]
    pub fn unlimited() -> Self {
        Self(Arc::new(Mutex::new(TokenBucket::new(None))))
    }

    /// A cap of `bytes_per_second`.
    #[must_use]
    pub fn limited(bytes_per_second: u64) -> Self {
        Self(Arc::new(Mutex::new(TokenBucket::new(Some(
            bytes_per_second,
        )))))
    }

    /// Sets the cap (`None` lifts it). Takes effect from the next chunk.
    pub fn set_limit(&self, bytes_per_second: Option<u64>) {
        self.bucket().set_rate(bytes_per_second, Instant::now());
    }

    #[must_use]
    pub fn limit(&self) -> Option<u64> {
        self.bucket().rate()
    }

    /// Waits until `bytes` may be sent.
    pub async fn acquire(&self, bytes: usize) {
        let wait = self.bucket().reserve(bytes, Instant::now());
        if !wait.is_zero() {
            tokio::time::sleep(wait).await;
        }
    }

    fn bucket(&self) -> std::sync::MutexGuard<'_, TokenBucket> {
        self.0.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(value: f64) -> Duration {
        Duration::from_secs_f64(value)
    }

    fn close(actual: Duration, expected: Duration) -> bool {
        actual.abs_diff(expected) < Duration::from_millis(1)
    }

    #[test]
    fn unlimited_never_waits() {
        let mut bucket = TokenBucket::new(None);
        assert_eq!(bucket.reserve(50_000_000, Instant::now()), Duration::ZERO);
    }

    #[test]
    fn a_full_bucket_sends_one_burst_then_paces_at_the_rate() {
        let start = Instant::now();
        let mut bucket = TokenBucket::new(Some(100_000));
        // Burst: a quarter second's worth.
        assert_eq!(bucket.reserve(25_000, start), Duration::ZERO);
        assert!(close(bucket.reserve(50_000, start), secs(0.5)));
        // Waiting the half second pays the debt; the next 10 kB wait 0.1 s.
        assert!(close(bucket.reserve(10_000, start + secs(0.5)), secs(0.1)));
    }

    #[test]
    fn the_average_rate_never_exceeds_the_cap() {
        let start = Instant::now();
        let mut bucket = TokenBucket::new(Some(100_000));
        let mut now = start;
        for _ in 0..16 {
            now += bucket.reserve(65_536, now);
        }
        // 1 MiB at 100 kB/s, less the 25 kB burst.
        let expected = (16.0 * 65_536.0 - 25_000.0) / 100_000.0;
        assert!(close(now - start, secs(expected)), "{:?}", now - start);
    }

    #[test]
    fn idle_time_refills_only_up_to_the_burst() {
        let start = Instant::now();
        let mut bucket = TokenBucket::new(Some(100_000));
        bucket.reserve(25_000, start);
        let later = start + Duration::from_secs(60);
        assert_eq!(bucket.reserve(25_000, later), Duration::ZERO);
        assert!(close(bucket.reserve(10_000, later), secs(0.1)));
    }

    #[test]
    fn lowering_the_cap_slows_the_next_chunks() {
        let start = Instant::now();
        let mut bucket = TokenBucket::new(Some(100_000));
        bucket.reserve(25_000, start);
        bucket.set_rate(Some(20_000), start);
        assert!(close(bucket.reserve(10_000, start), secs(0.5)));
        bucket.set_rate(None, start);
        assert_eq!(bucket.reserve(10_000_000, start), Duration::ZERO);
    }

    #[test]
    fn small_caps_still_allow_a_chunk_of_burst() {
        let mut bucket = TokenBucket::new(Some(1_000));
        assert_eq!(bucket.reserve(16 * 1024, Instant::now()), Duration::ZERO);
    }

    #[test]
    fn a_zero_cap_means_unlimited() {
        assert_eq!(TokenBucket::new(Some(0)).rate(), None);
        let shared = Bandwidth::limited(50_000);
        assert_eq!(shared.limit(), Some(50_000));
        shared.set_limit(None);
        assert_eq!(shared.clone().limit(), None);
    }
}
