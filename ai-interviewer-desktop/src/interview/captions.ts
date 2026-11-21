/**
 * The interviewer's live caption (product owner, 2026-11-16): what the AI is saying right now,
 * at most 250 characters. As it keeps speaking, the oldest words leave and the text moves up.
 * It shows only while the AI speaks; the candidate's own words are never shown.
 */

export const CAPTION_MAX = 250;

/** The last `max` characters of `spoken`, starting at a whole word, on single spaces. */
export function captionWindow(spoken: string, max: number = CAPTION_MAX): string {
  const clean = spoken.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const tail = clean.slice(clean.length - (max - 1));
  const space = tail.indexOf(" ");
  // Drop the cut-off first word, unless the tail is one long word.
  const whole = space >= 0 && space < tail.length - 1 ? tail.slice(space + 1) : tail;
  return `…${whole}`;
}

/** LiveKit sends both sides' transcriptions on one topic: only the interviewer's is a caption. */
export function isInterviewerCaption(speaker: string, candidate: string): boolean {
  return speaker !== candidate;
}
