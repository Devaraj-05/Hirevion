/** The evaluation panel's logic, kept apart from the components (SP-10): validating a reviewer's
 * scores, when the AI's numbers are shown next to them, and how to word the organisation's
 * agreement. */

/** PRD §44's eight dimensions, in the order the API returns them. */
export const DIMENSIONS = [
  "relevance",
  "correctness",
  "completeness",
  "technical_depth",
  "reasoning",
  "clarity",
  "communication",
  "evidence",
] as const;
export type Dimension = (typeof DIMENSIONS)[number];

/** What a dimension without a verified quote is capped at (the API's `UNSUPPORTED_CAP`). */
export const UNSUPPORTED_CAP = 5;
/** Fewer pairs than this says nothing about agreement. */
export const MIN_PAIRS = 10;

export type ScoreDraft = Partial<Record<Dimension, string>>;
export type ScoreError = "invalid" | "range";

export interface ValidatedScores {
  /** The dimensions the reviewer filled in, as numbers to send. */
  scores: Partial<Record<Dimension, number>>;
  errors: Partial<Record<Dimension, ScoreError>>;
  /** Whether it can be saved: something is filled in and nothing is wrong. */
  ok: boolean;
}

/** One score from what was typed: blank is "not scored"; scores run from 0 to 10, and a
 * decimal comma is accepted. */
export function parseScore(input: string): { value: number } | { error: ScoreError } | null {
  const text = input.trim().replace(",", ".");
  if (text === "") return null;
  if (!/^\d+(\.\d+)?$/.test(text)) return { error: "invalid" };
  const value = Number(text);
  if (value < 0 || value > 10) return { error: "range" };
  return { value: Math.round(value * 10) / 10 };
}

export function validateScores(draft: ScoreDraft): ValidatedScores {
  const scores: Partial<Record<Dimension, number>> = {};
  const errors: Partial<Record<Dimension, ScoreError>> = {};
  for (const dimension of DIMENSIONS) {
    const parsed = parseScore(draft[dimension] ?? "");
    if (parsed === null) continue;
    if ("error" in parsed) errors[dimension] = parsed.error;
    else scores[dimension] = parsed.value;
  }
  return {
    scores,
    errors,
    ok: Object.keys(scores).length > 0 && Object.keys(errors).length === 0,
  };
}

/** The draft to edit from scores already saved. */
export function draftFrom(saved: Partial<Record<string, number>> | undefined): ScoreDraft {
  const draft: ScoreDraft = {};
  for (const dimension of DIMENSIONS) {
    const value = saved?.[dimension];
    if (value !== undefined) draft[dimension] = String(value);
  }
  return draft;
}

/** Whether the AI's scores for a question are shown beside the reviewer's: only once they have
 * saved their own, so the AI's numbers don't set theirs. */
export function revealsAi(savedOwn: boolean): boolean {
  return savedOwn;
}

/** The AI's score minus the reviewer's, per dimension both scored. */
export function gaps(
  ai: Partial<Record<string, number>>,
  own: Partial<Record<string, number>>,
): Partial<Record<Dimension, number>> {
  const result: Partial<Record<Dimension, number>> = {};
  for (const dimension of DIMENSIONS) {
    const a = ai[dimension];
    const h = own[dimension];
    if (a !== undefined && h !== undefined) result[dimension] = Math.round((a - h) * 10) / 10;
  }
  return result;
}

export type AgreementLevel = "insufficient" | "strong" | "moderate" | "weak";

/** How to word weighted kappa (Landis and Koch's bands, rounded to the ones people use). */
export function agreementLevel(stats: {
  n: number;
  weighted_kappa: number | null;
}): AgreementLevel {
  if (stats.n < MIN_PAIRS || stats.weighted_kappa === null) return "insufficient";
  if (stats.weighted_kappa >= 0.8) return "strong";
  if (stats.weighted_kappa >= 0.6) return "moderate";
  return "weak";
}

/** A score for display: one decimal, or a dash where there is none. */
export function formatScore(score: number | null | undefined): string {
  return score === null || score === undefined ? "–" : score.toFixed(1);
}

/** A time in the transcript as m:ss (the quote's place in the interview). */
export function clock(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${Math.floor(seconds / 60)}:${pad(seconds % 60)}`;
}
