//! Frame timing for fixed-rate recording, in Media Foundation's 100 ns units.

/// Media Foundation time units per second (100 ns ticks).
pub const TICKS_PER_SECOND: i64 = 10_000_000;

/// Where a frame falls: which segment, and its index inside that segment.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SegmentPosition {
    pub seq: u64,
    pub index: u32,
}

/// Fixed-rate frame timing. Times are computed from the frame number, so they never drift.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FrameClock {
    fps: u32,
    frames_per_segment: u32,
}

impl FrameClock {
    /// `None` when the rate or the segment length is zero.
    #[must_use]
    pub fn new(fps: u32, segment_seconds: u32) -> Option<Self> {
        let frames_per_segment = fps.checked_mul(segment_seconds)?;
        (frames_per_segment > 0).then_some(Self {
            fps,
            frames_per_segment,
        })
    }

    #[must_use]
    pub fn fps(&self) -> u32 {
        self.fps
    }

    #[must_use]
    pub fn frames_per_segment(&self) -> u32 {
        self.frames_per_segment
    }

    /// Presentation time of `frame` since recording started.
    #[must_use]
    pub fn sample_time(&self, frame: u64) -> i64 {
        let ticks = i128::from(frame) * i128::from(TICKS_PER_SECOND) / i128::from(self.fps);
        i64::try_from(ticks).unwrap_or(i64::MAX)
    }

    /// Duration of `frame`; consecutive durations add up to exact seconds.
    #[must_use]
    pub fn frame_duration(&self, frame: u64) -> i64 {
        self.sample_time(frame + 1) - self.sample_time(frame)
    }

    #[must_use]
    pub fn position(&self, frame: u64) -> SegmentPosition {
        let per_segment = u64::from(self.frames_per_segment);
        let index = u32::try_from(frame % per_segment).unwrap_or(u32::MAX);
        SegmentPosition {
            seq: frame / per_segment,
            index,
        }
    }

    /// Presentation time of `frame` inside its own segment (each segment starts at zero).
    #[must_use]
    pub fn segment_time(&self, frame: u64) -> i64 {
        let first = frame - u64::from(self.position(frame).index);
        self.sample_time(frame) - self.sample_time(first)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn clock() -> FrameClock {
        FrameClock::new(15, 10).expect("valid clock")
    }

    #[test]
    fn rejects_zero_rates_and_lengths() {
        assert!(FrameClock::new(0, 10).is_none());
        assert!(FrameClock::new(15, 0).is_none());
    }

    #[test]
    fn maps_frames_to_segments() {
        let clock = clock();
        assert_eq!(clock.frames_per_segment(), 150);
        assert_eq!(clock.position(149), SegmentPosition { seq: 0, index: 149 });
        assert_eq!(clock.position(150), SegmentPosition { seq: 1, index: 0 });
    }

    #[test]
    fn sample_times_never_drift() {
        assert_eq!(clock().sample_time(15 * 3600), 3600 * TICKS_PER_SECOND);
    }

    #[test]
    fn one_second_of_durations_sums_exactly() {
        let clock = clock();
        let total: i64 = (7..7 + 15).map(|frame| clock.frame_duration(frame)).sum();
        assert_eq!(total, TICKS_PER_SECOND);
    }

    #[test]
    fn segment_times_restart_at_zero() {
        let clock = clock();
        assert_eq!(clock.segment_time(150), 0);
        assert_eq!(clock.segment_time(151), 666_666);
        assert_eq!(clock.segment_time(299), clock.sample_time(149));
    }
}
