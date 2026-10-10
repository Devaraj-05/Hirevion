//! Where screen segments sit on the interview's timeline: track names, and segment start
//! times in server milliseconds, so the media worker can line screens up with the camera and
//! microphone (recordings contract: `started_at`, `duration_ms`).

use std::time::Instant;

use crate::clock::{FrameClock, TICKS_PER_SECOND};

/// Track names for displays in Windows' order, given which one is primary: the primary
/// display is `screen-1`, the others follow in order. Returns `(display index, track)` in
/// track order.
#[must_use]
pub fn screen_tracks(primary: &[bool]) -> Vec<(usize, String)> {
    let mut order: Vec<usize> = (0..primary.len()).collect();
    // A stable sort keeps Windows' order among the secondary displays.
    order.sort_by_key(|&index| !primary[index]);
    order
        .into_iter()
        .enumerate()
        .map(|(position, index)| (index, format!("screen-{}", position + 1)))
        .collect()
}

/// The server time of `at`, given that `start` was `origin_ms` on the server's clock.
#[must_use]
pub fn server_ms_at(origin_ms: i64, start: Instant, at: Instant) -> i64 {
    let elapsed =
        i64::try_from(at.saturating_duration_since(start).as_millis()).unwrap_or(i64::MAX);
    origin_ms.saturating_add(elapsed)
}

/// How long `frames` frames play, in whole milliseconds (rounded to nearest).
#[must_use]
pub fn duration_ms(clock: &FrameClock, frames: u32) -> u32 {
    let ticks = clock.sample_time(u64::from(frames));
    let per_ms = TICKS_PER_SECOND / 1_000;
    u32::try_from((ticks + per_ms / 2) / per_ms).unwrap_or(u32::MAX)
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[test]
    fn the_primary_display_is_screen_1() {
        assert_eq!(
            screen_tracks(&[false, true, false]),
            [
                (1, "screen-1".to_owned()),
                (0, "screen-2".to_owned()),
                (2, "screen-3".to_owned())
            ]
        );
        assert_eq!(screen_tracks(&[true]), [(0, "screen-1".to_owned())]);
        assert!(screen_tracks(&[]).is_empty());
    }

    #[test]
    fn a_full_segment_lasts_exactly_its_length() {
        let clock = FrameClock::new(15, 10).expect("clock");
        assert_eq!(duration_ms(&clock, 150), 10_000);
        assert_eq!(duration_ms(&clock, 149), 9_933);
        assert_eq!(duration_ms(&clock, 1), 67);
        assert_eq!(duration_ms(&clock, 0), 0);
    }

    #[test]
    fn ticks_map_onto_the_server_clock() {
        let start = Instant::now();
        let origin = 1_700_000_000_000;
        assert_eq!(server_ms_at(origin, start, start), origin);
        assert_eq!(
            server_ms_at(origin, start, start + Duration::from_millis(10_000)),
            origin + 10_000
        );
        // A tick can't come before the start; it is clamped rather than wrapped.
        assert_eq!(
            server_ms_at(origin, start + Duration::from_secs(1), start),
            origin
        );
    }

    #[test]
    fn segment_starts_follow_the_real_ticks_without_drift() {
        // Four hours of 10-second segments whose first frame lands up to a frame late.
        let clock = FrameClock::new(15, 10).expect("clock");
        let start = Instant::now();
        let origin = 1_700_000_000_000;
        for seq in 0..1_440u64 {
            let nominal_ticks = clock.sample_time(seq * u64::from(clock.frames_per_segment()));
            let nominal =
                Duration::from_nanos(u64::try_from(nominal_ticks).expect("positive") * 100);
            let late = Duration::from_millis(seq * 7 % 67);
            let started = server_ms_at(origin, start, start + nominal + late);
            let expected = origin + i64::try_from(seq).expect("small") * 10_000;
            assert!(
                (started - expected).abs() < 67,
                "segment {seq}: {started} vs {expected}"
            );
        }
    }
}
