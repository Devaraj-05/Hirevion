import { describe, expect, it } from "vitest";
import { controlMessage, formatClock, mergeState, parseStateMessage } from "./session";

const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));

const STATE = {
  status: "in_progress",
  remaining_seconds: 2700,
  answer_mode: "voice" as const,
  question: null,
  voice: "waiting" as const,
  stage: "start",
  message: null,
  notice: null,
};

describe("the agent's hv.state messages", () => {
  it("reads the voice state, the question and the time left", () => {
    const patch = parseStateMessage(
      encode({
        voice: "speaking",
        question: {
          id: "q1",
          index: 1,
          text: "Hi",
          type: "technical",
          time_limit_seconds: 300,
          workspace: "none",
          languages: [],
        },
        remaining_seconds: 2600,
        notice: null,
      }),
    );
    expect(patch).toMatchObject({ voice: "speaking", remaining_seconds: 2600 });
    expect(mergeState(STATE, patch ?? {})).toMatchObject({
      voice: "speaking",
      question: { id: "q1" },
    });
  });

  it("ignores malformed or unknown messages instead of crashing the screen", () => {
    expect(parseStateMessage(new TextEncoder().encode("not json"))).toBeNull();
    expect(parseStateMessage(encode({ voice: "dancing" }))).toEqual({});
    expect(parseStateMessage(encode([1, 2]))).toBeNull();
  });
});

describe("the candidate's controls (hv.control)", () => {
  it("encodes the three actions the agent understands", () => {
    expect(new TextDecoder().decode(controlMessage("need_a_moment"))).toBe(
      '{"action":"need_a_moment"}',
    );
  });
});

describe("the interview clock", () => {
  it("shows minutes and seconds, never below zero", () => {
    expect(formatClock(2700)).toBe("45:00");
    expect(formatClock(61)).toBe("01:01");
    expect(formatClock(-5)).toBe("00:00");
  });
});
