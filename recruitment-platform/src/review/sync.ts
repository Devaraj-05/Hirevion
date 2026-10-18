/**
 * The review player's clock (SP-17; PRD §71). One clock counts milliseconds from when the
 * interview started (`anchor`, the transcript's own origin). Each recording is a file whose
 * position maps onto it through the track's timeline map (`docs/api/contracts/recordings.md`):
 * a segment started at a server time and sits at an offset in the assembled file, and a gap
 * (a missing segment) has no file position. Pure functions, so every mapping is tested.
 */

export interface MapSegment {
  seq: number;
  started_at: string;
  duration_ms: number;
  file_offset_ms: number;
}

export interface TrackTiming {
  started_at: string | null;
  duration_ms: number | null;
  /** The track's timeline map; null for a file with none (an Egress recording, or a map that
   * couldn't be read), which is taken to run from `started_at` without a break. */
  timeline: { segments?: MapSegment[] } | Record<string, unknown> | null;
}

function segmentsOf(timing: TrackTiming): MapSegment[] | null {
  const segments = (timing.timeline as { segments?: MapSegment[] } | null)?.segments;
  return Array.isArray(segments) && segments.length > 0 ? segments : null;
}

function time(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/** Where in the track's file the interview was at `offsetMs`, or null when the track recorded
 * nothing then (a gap, before it began or after it ended). */
export function filePosition(
  anchor: string | null,
  offsetMs: number,
  timing: TrackTiming,
): number | null {
  const origin = time(anchor);
  if (origin === null) return null;
  const moment = origin + offsetMs;
  const segments = segmentsOf(timing);
  if (segments) {
    for (const segment of segments) {
      const start = time(segment.started_at);
      if (start === null) continue;
      if (moment >= start && moment < start + segment.duration_ms) {
        return segment.file_offset_ms + (moment - start);
      }
    }
    return null;
  }
  const start = time(timing.started_at);
  if (start === null) return null;
  const position = moment - start;
  if (position < 0) return null;
  if (timing.duration_ms !== null && position > timing.duration_ms) return null;
  return position;
}

/** The interview offset of a position in the track's file, or null if the file has nothing
 * there. The inverse of `filePosition`. */
export function offsetFromFile(
  anchor: string | null,
  position: number,
  timing: TrackTiming,
): number | null {
  const origin = time(anchor);
  if (origin === null) return null;
  const segments = segmentsOf(timing);
  if (segments) {
    for (const segment of segments) {
      const start = time(segment.started_at);
      if (start === null) continue;
      if (
        position >= segment.file_offset_ms &&
        position < segment.file_offset_ms + segment.duration_ms
      ) {
        return start + (position - segment.file_offset_ms) - origin;
      }
    }
    return null;
  }
  const start = time(timing.started_at);
  return start === null ? null : start + position - origin;
}

/** How far into the interview an event (a proctoring event, a note) happened. */
export function eventOffset(anchor: string | null, startedAt: string): number | null {
  const origin = time(anchor);
  const moment = time(startedAt);
  return origin === null || moment === null ? null : moment - origin;
}

/** The end of the timeline: where the last recording ends, else `fallback` (the interview's
 * own length). */
export function timelineEnd(
  anchor: string | null,
  tracks: readonly TrackTiming[],
  fallback: number,
): number {
  const origin = time(anchor);
  let end = fallback;
  if (origin === null) return end;
  for (const track of tracks) {
    const segments = segmentsOf(track);
    if (segments) {
      for (const segment of segments) {
        const start = time(segment.started_at);
        if (start !== null) end = Math.max(end, start + segment.duration_ms - origin);
      }
      continue;
    }
    const start = time(track.started_at);
    if (start !== null && track.duration_ms !== null) {
      end = Math.max(end, start + track.duration_ms - origin);
    }
  }
  return end;
}

/** A time within the interview: 1:02 or 1:02:03. */
export function clock(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}
