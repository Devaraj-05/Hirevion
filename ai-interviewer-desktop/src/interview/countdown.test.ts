import { describe, expect, it } from "vitest";
import { announcement, clockTone, reconcile } from "./countdown";

describe("the countdown (C8-12)", () => {
  it("turns amber at five minutes and red at two", () => {
    expect(clockTone(301)).toBe("normal");
    expect(clockTone(300)).toBe("low");
    expect(clockTone(121)).toBe("low");
    expect(clockTone(120)).toBe("critical");
    expect(clockTone(0)).toBe("critical");
  });

  it("keeps its own tick unless the server's time differs by more than two seconds", () => {
    // The agent's refresh every 5 s made the clock jump back and forth by a second or two.
    expect(reconcile(1712, 1714)).toBe(1712);
    expect(reconcile(1712, 1710)).toBe(1712);
    expect(reconcile(1712, 1700)).toBe(1700);
    expect(reconcile(40, 160)).toBe(160);
  });

  it("announces five minutes and one minute left, once each", () => {
    expect(announcement(301, 300)).toBe(5);
    expect(announcement(300, 299)).toBeNull();
    expect(announcement(61, 60)).toBe(1);
    expect(announcement(1712, 1711)).toBeNull();
    // A jump across the mark (the server's time) still announces it.
    expect(announcement(320, 290)).toBe(5);
  });
});
