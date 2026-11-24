/**
 * The interview's live transcript (C8-12, owner 2026-11-22): both voices, written as they are
 * spoken. LiveKit sends each utterance as a text stream on `lk.transcription`, named by its
 * segment (`lk.segment_id`): interim words replace each other, and the final words
 * (`lk.transcription_final`) stay. This replaces ADR-0044's 250-character caption.
 */

export type Speaker = "interviewer" | "candidate";

export interface Line {
  /** The segment it came from: later words for the same segment replace these. */
  id: string;
  speaker: Speaker;
  text: string;
  /** False while the words may still change. */
  final: boolean;
}

/** An interview's worth of turns; older lines leave the screen. */
export const TRANSCRIPT_MAX = 200;

export const SEGMENT_ID = "lk.segment_id";
export const SEGMENT_FINAL = "lk.transcription_final";
export const TRANSCRIBED_TRACK = "lk.transcribed_track_id";

/**
 * `lines` with `segment` written in: a known segment is replaced where it is (unless its final
 * words are already there), a new one goes at the end, and silence is skipped. Returns `lines`
 * itself when nothing changed.
 */
export function upsert(
  lines: readonly Line[],
  segment: Line,
  max: number = TRANSCRIPT_MAX,
): Line[] {
  const text = segment.text.replace(/\s+/g, " ").trim();
  const at = lines.findIndex((one) => one.id === segment.id);
  const known = at >= 0 ? lines[at] : undefined;
  if (!text || (known?.final && !segment.final)) return lines as Line[];
  const next = { ...segment, text };
  if (known) {
    const copy = [...lines];
    copy[at] = next;
    return copy;
  }
  return [...lines, next].slice(-max);
}

/**
 * Who said it. The candidate's own words come back from the interviewer agent, which sends them
 * on the candidate's identity or names the candidate's microphone track.
 */
export function speakerOf(
  sender: string,
  candidate: string,
  transcribedTrack: string | undefined,
  candidateTracks: readonly string[],
): Speaker {
  if (sender === candidate) return "candidate";
  if (transcribedTrack && candidateTracks.includes(transcribedTrack)) return "candidate";
  return "interviewer";
}

/** The line being spoken now (the newest), the only one that carries its speaker's colour. */
export function activeLine(lines: readonly Line[]): string | null {
  return lines.at(-1)?.id ?? null;
}

export function isFinalSegment(attributes: Record<string, string> | undefined): boolean {
  return attributes?.[SEGMENT_FINAL] === "true";
}
