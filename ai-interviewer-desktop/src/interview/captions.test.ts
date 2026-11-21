import { describe, expect, it } from "vitest";
import { CAPTION_MAX, captionWindow, isInterviewerCaption } from "./captions";

describe("the interviewer's live caption", () => {
  it("shows short speech whole, on one line of spaces", () => {
    expect(captionWindow("  Let's begin   with Python.\nWhat is a tuple? ")).toBe(
      "Let's begin with Python. What is a tuple?",
    );
  });

  it("keeps only the last 250 characters, from a whole word, so the text moves up as it is spoken", () => {
    const spoken = Array.from({ length: 80 }, (_, index) => `word${index}`).join(" ");
    const shown = captionWindow(spoken);
    expect(shown.length).toBeLessThanOrEqual(CAPTION_MAX);
    expect(shown.endsWith("word79")).toBe(true);
    expect(shown.startsWith("…word")).toBe(true); // an ellipsis, then a whole word
    expect(spoken.endsWith(shown.slice(1))).toBe(true);
  });

  it("never goes over the limit, even for one very long word", () => {
    expect(captionWindow("x".repeat(600)).length).toBe(CAPTION_MAX);
  });
});

describe("whose words are shown", () => {
  it("shows the interviewer's, never the candidate's own transcription", () => {
    expect(isInterviewerCaption("agent-AJ_1", "candidate-7")).toBe(true);
    expect(isInterviewerCaption("candidate-7", "candidate-7")).toBe(false);
  });
});
