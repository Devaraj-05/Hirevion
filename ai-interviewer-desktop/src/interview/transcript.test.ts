import { describe, expect, it } from "vitest";
import { isFinalSegment, type Line, speakerOf, TRANSCRIPT_MAX, upsert } from "./transcript";

const line = (
  id: string,
  text: string,
  final = true,
  speaker: Line["speaker"] = "interviewer",
) => ({
  id,
  speaker,
  text,
  final,
});

describe("the live transcript (C8-12)", () => {
  it("writes both speakers, the candidate's own words included", () => {
    // Before C8-12 the candidate's stream was dropped; now it is shown on the right as "You".
    expect(speakerOf("agent-1", "candidate-7", undefined, [])).toBe("interviewer");
    expect(speakerOf("candidate-7", "candidate-7", undefined, [])).toBe("candidate");
    // The agent sends the candidate's transcript on its own identity, naming the candidate's
    // microphone track.
    expect(speakerOf("agent-1", "candidate-7", "TR_mic", ["TR_mic", "TR_cam"])).toBe("candidate");
  });

  it("replaces an interim line by its segment until the final words arrive", () => {
    let lines: Line[] = [];
    lines = upsert(lines, line("s1", "I built", false, "candidate"));
    lines = upsert(lines, line("s1", "I built an order  service", false, "candidate"));
    expect(lines).toEqual([line("s1", "I built an order service", false, "candidate")]);
    lines = upsert(lines, line("s1", "I built an order service on a queue.", true, "candidate"));
    expect(lines).toEqual([line("s1", "I built an order service on a queue.", true, "candidate")]);
  });

  it("never lets a late interim undo the final words", () => {
    const lines = [line("s1", "I built an order service.")];
    expect(upsert(lines, line("s1", "I built", false))).toBe(lines);
  });

  it("keeps the order lines started in, adds new segments at the end, and skips silence", () => {
    let lines: Line[] = [line("a", "Tell me about Redis.")];
    lines = upsert(lines, line("b", "Sure.", true, "candidate"));
    lines = upsert(lines, line("a", "Tell me about Redis caching."));
    expect(lines.map((one) => one.id)).toEqual(["a", "b"]);
    expect(upsert(lines, line("c", "   "))).toBe(lines);
  });

  it(`keeps the last ${TRANSCRIPT_MAX} lines`, () => {
    let lines: Line[] = [];
    for (let n = 0; n < TRANSCRIPT_MAX + 5; n += 1)
      lines = upsert(lines, line(`s${n}`, `line ${n}`));
    expect(lines).toHaveLength(TRANSCRIPT_MAX);
    expect(lines[0]?.id).toBe("s5");
  });

  it("reads LiveKit's final flag from the stream's attributes", () => {
    expect(isFinalSegment({ "lk.transcription_final": "true" })).toBe(true);
    expect(isFinalSegment({ "lk.transcription_final": "false" })).toBe(false);
    expect(isFinalSegment(undefined)).toBe(false);
  });
});
