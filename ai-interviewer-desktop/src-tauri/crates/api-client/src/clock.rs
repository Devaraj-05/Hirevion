use std::sync::{Mutex, PoisonError};

use serde::Serialize;

/// One server-time measurement (the NTP estimate from `GET /time`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ClockSample {
    /// Server time minus local time, in milliseconds.
    pub offset_ms: i64,
    /// The network round trip, excluding the server's own processing time.
    pub round_trip_ms: i64,
}

impl ClockSample {
    /// The estimate from four timestamps: `t0` local send, `t1` server receive, `t2` server
    /// send, `t3` local receive. Offset = ((t1 − t0) + (t2 − t3)) / 2,
    /// round trip = (t3 − t0) − (t2 − t1).
    pub fn from_timestamps(t0: i64, t1: i64, t2: i64, t3: i64) -> Self {
        Self {
            offset_ms: ((t1 - t0) + (t2 - t3)) / 2,
            round_trip_ms: ((t3 - t0) - (t2 - t1)).max(0),
        }
    }
}

/// Keeps the sample with the shortest round trip: the one with the smallest error bound.
#[derive(Debug, Default)]
pub(crate) struct Clock {
    best: Mutex<Option<ClockSample>>,
}

impl Clock {
    pub(crate) fn record(&self, sample: ClockSample) {
        let mut best = self.best.lock().unwrap_or_else(PoisonError::into_inner);
        if best.is_none_or(|b| sample.round_trip_ms < b.round_trip_ms) {
            *best = Some(sample);
        }
    }

    pub(crate) fn best(&self) -> Option<ClockSample> {
        *self.best.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Local wall-clock time in milliseconds since the Unix epoch.
pub(crate) fn local_now_ms() -> i64 {
    match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
        Ok(since) => i64::try_from(since.as_millis()).unwrap_or(i64::MAX),
        Err(before) => -i64::try_from(before.duration().as_millis()).unwrap_or(i64::MAX),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_the_sample_with_the_shortest_round_trip() {
        let clock = Clock::default();
        assert_eq!(clock.best(), None);
        let slow = ClockSample {
            offset_ms: 100,
            round_trip_ms: 80,
        };
        let fast = ClockSample {
            offset_ms: 120,
            round_trip_ms: 20,
        };
        let slower = ClockSample {
            offset_ms: 500,
            round_trip_ms: 300,
        };
        clock.record(slow);
        assert_eq!(clock.best(), Some(slow));
        clock.record(fast);
        assert_eq!(clock.best(), Some(fast));
        clock.record(slower);
        assert_eq!(clock.best(), Some(fast));
    }

    #[test]
    fn a_negative_round_trip_is_clamped() {
        // Server timestamps that claim more processing time than the whole exchange took.
        let sample = ClockSample::from_timestamps(0, 10, 100, 50);
        assert_eq!(sample.round_trip_ms, 0);
    }
}
