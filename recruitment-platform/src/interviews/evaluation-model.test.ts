import { describe, expect, it } from "vitest";
import {
  agreementLevel,
  clock,
  DIMENSIONS,
  draftFrom,
  formatScore,
  gaps,
  mergeScores,
  parseScore,
  summaryRevealed,
  validateScores,
} from "./evaluation-model";

describe("parseScore", () => {
  it("reads whole and decimal scores, with a comma too, and treats blank as not scored", () => {
    expect(parseScore("7")).toEqual({ value: 7 });
    expect(parseScore(" 7.5 ")).toEqual({ value: 7.5 });
    expect(parseScore("6,25")).toEqual({ value: 6.3 });
    expect(parseScore("0")).toEqual({ value: 0 });
    expect(parseScore("10")).toEqual({ value: 10 });
    expect(parseScore("   ")).toBeNull();
  });

  it("refuses what isn't a score from 0 to 10", () => {
    expect(parseScore("11")).toEqual({ error: "range" });
    expect(parseScore("10.1")).toEqual({ error: "range" });
    expect(parseScore("-1")).toEqual({ error: "invalid" });
    expect(parseScore("high")).toEqual({ error: "invalid" });
    expect(parseScore("7/10")).toEqual({ error: "invalid" });
  });
});

describe("validateScores", () => {
  it("keeps the dimensions filled in and can be saved when none is wrong", () => {
    const result = validateScores({ correctness: "8", clarity: "6.5", reasoning: "" });
    expect(result).toEqual({
      scores: { correctness: 8, clarity: 6.5 },
      errors: {},
      ok: true,
    });
  });

  it("can't be saved empty or with a wrong score, and says which", () => {
    expect(validateScores({}).ok).toBe(false);
    const wrong = validateScores({ correctness: "8", clarity: "eleven", evidence: "12" });
    expect(wrong.ok).toBe(false);
    expect(wrong.errors).toEqual({ clarity: "invalid", evidence: "range" });
    expect(wrong.scores).toEqual({ correctness: 8 });
  });
});

describe("draftFrom and gaps", () => {
  it("edits from what was saved, in the dimensions' order", () => {
    expect(draftFrom({ clarity: 6.5, correctness: 8, unknown: 3 })).toEqual({
      correctness: "8",
      clarity: "6.5",
    });
    expect(draftFrom(undefined)).toEqual({});
    expect(DIMENSIONS).toHaveLength(8);
  });

  it("is the AI's score minus the reviewer's, where both scored", () => {
    expect(
      gaps({ correctness: 9, clarity: 6, reasoning: 4 }, { correctness: 7.5, clarity: 7 }),
    ).toEqual({
      correctness: 1.5,
      clarity: -1,
    });
  });
});

describe("summaryRevealed", () => {
  it("keeps the AI's numbers back until every question has the reviewer's scores", () => {
    expect(summaryRevealed({ saved: 0, total: 3 }, false)).toBe(false);
    expect(summaryRevealed({ saved: 2, total: 3 }, false)).toBe(false);
    expect(summaryRevealed({ saved: 3, total: 3 }, false)).toBe(true);
  });

  it("shows them when the reviewer chose to skip scoring, or there is nothing to score", () => {
    expect(summaryRevealed({ saved: 0, total: 3 }, true)).toBe(true);
    expect(summaryRevealed({ saved: 0, total: 0 }, false)).toBe(true);
  });
});

describe("mergeScores", () => {
  it("keeps the saved dimensions the reviewer didn't touch", () => {
    expect(mergeScores({ correctness: 8, clarity: 6 }, { clarity: 7, evidence: 5 })).toEqual({
      correctness: 8,
      clarity: 7,
      evidence: 5,
    });
    expect(mergeScores(undefined, { clarity: 7 })).toEqual({ clarity: 7 });
  });
});

describe("agreementLevel", () => {
  it("needs enough pairs and a kappa", () => {
    expect(agreementLevel({ n: 9, weighted_kappa: 0.95 })).toBe("insufficient");
    expect(agreementLevel({ n: 40, weighted_kappa: null })).toBe("insufficient");
  });

  it("words kappa in three bands", () => {
    expect(agreementLevel({ n: 40, weighted_kappa: 0.82 })).toBe("strong");
    expect(agreementLevel({ n: 40, weighted_kappa: 0.8 })).toBe("strong");
    expect(agreementLevel({ n: 40, weighted_kappa: 0.65 })).toBe("moderate");
    expect(agreementLevel({ n: 40, weighted_kappa: 0.4 })).toBe("weak");
    expect(agreementLevel({ n: 40, weighted_kappa: -0.2 })).toBe("weak");
  });
});

describe("display helpers", () => {
  it("formats scores and times", () => {
    expect(formatScore(7)).toBe("7.0");
    expect(formatScore(null)).toBe("–");
    expect(formatScore(undefined)).toBe("–");
    expect(clock(83_000)).toBe("1:23");
    expect(clock(5_000)).toBe("0:05");
  });
});
