export interface Placement {
  segment: number;
  /** Microseconds since the start of `segment`. */
  offsetUs: number;
}

/**
 * Places capture timestamps (microseconds) into fixed-length segments. The first timestamp
 * seen becomes time zero; earlier ones are clamped to it.
 */
export class SegmentClock {
  private origin: number | null = null;

  constructor(readonly segmentUs: number) {}

  place(timestampUs: number): Placement {
    this.origin ??= timestampUs;
    const elapsed = Math.max(0, timestampUs - this.origin);
    const segment = Math.floor(elapsed / this.segmentUs);
    return { segment, offsetUs: elapsed - segment * this.segmentUs };
  }
}
