/**
 * The arithmetic behind the interview analytics charts (C8-7, ADR-0047): axis ceilings,
 * positions on the interview's timeline and the answer-timing bars. Kept apart from the
 * components so it can be tested without rendering.
 */

/** Rounds an axis maximum up to 1, 2 or 5 times a power of ten (at least 1). */
export function niceCeiling(value: number): number {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((factor) => factor * power >= value) ?? 10;
  return step * power;
}

/** Where `offsetMs` falls along an interview of `durationMs`, as a percentage (0 to 100). */
export function timelinePercent(offsetMs: number | null, durationMs: number | null): number | null {
  if (offsetMs === null || durationMs === null || durationMs <= 0) return null;
  return Math.min(100, Math.max(0, (offsetMs / durationMs) * 100));
}

interface Timed {
  position: number;
  thinking_ms: number | null;
  speaking_ms: number;
}

export interface AnswerBar {
  position: number;
  /** Percentages of the longest answer's thinking plus speaking time. */
  thinking: number;
  speaking: number;
  thinkingMs: number | null;
  speakingMs: number;
}

/** Each answer's thinking and speaking time on one scale, rounded up from the longest answer
 * so the axis reads in clean numbers. */
export function answerBars(questions: readonly Timed[]): { max: number; rows: AnswerBar[] } {
  const total = (q: Timed) => (q.thinking_ms ?? 0) + q.speaking_ms;
  const max = niceCeiling(Math.max(0, ...questions.map(total)) / 1000) * 1000;
  const percent = (ms: number) => (max > 0 ? (ms / max) * 100 : 0);
  return {
    max,
    rows: questions.map((q) => ({
      position: q.position,
      thinking: percent(q.thinking_ms ?? 0),
      speaking: percent(q.speaking_ms),
      thinkingMs: q.thinking_ms,
      speakingMs: q.speaking_ms,
    })),
  };
}

/** The questions put to the candidate and answered: the charts leave out a question that was
 * skipped or still open when the interview ended. */
export function withAnswers<T extends { kind: string; status: string }>(
  questions: readonly T[],
): T[] {
  return questions.filter((q) => q.status === "answered");
}

/** Whole minutes and seconds of `ms` (rounded to the second). */
export function splitDuration(ms: number | null): { minutes: number; seconds: number } | null {
  if (ms === null) return null;
  const total = Math.round(ms / 1000);
  return { minutes: Math.floor(total / 60), seconds: total % 60 };
}
