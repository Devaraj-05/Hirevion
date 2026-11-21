import { describe, expect, it } from "vitest";
import type { Framing } from "./framing";
import { checkMessage, sameVerdict, type Verdict } from "./verdict";

const seen = (changes: Partial<Framing> = {}): Framing => ({
  person: "ok",
  laptop: "cut",
  portrait: false,
  green: false,
  personScore: 0.9,
  laptopScore: 0.6,
  personBox: null,
  laptopBox: null,
  extra: null,
  others: [],
  ...changes,
});
const verdict = (framing: Framing | null, green = false): Verdict => ({
  green,
  framing,
  evidence: null,
});

describe("what the status line under the phone's picture says", () => {
  it("asks to turn an upright phone before anything else", () => {
    expect(checkMessage(verdict(seen({ portrait: true, person: "missing" })))).toBe("portrait");
  });

  it("names what to fix, then waits for the picture to hold", () => {
    expect(checkMessage(verdict(null))).toBe("checking");
    expect(checkMessage(verdict(seen({ person: "missing" })))).toBe("personMissing");
    expect(checkMessage(verdict(seen()))).toBe("laptopCut");
    expect(checkMessage(verdict(seen({ laptop: "ok", green: true })))).toBe("hold");
    expect(checkMessage(verdict(seen({ laptop: "ok", green: true }), true))).toBe("green");
  });

  it("asks for another person or laptop to leave the picture", () => {
    expect(checkMessage(verdict(seen({ laptop: "ok", extra: "person" })))).toBe("extraPerson");
    expect(checkMessage(verdict(seen({ laptop: "ok", extra: "laptop" })))).toBe("extraLaptop");
    // The candidate first: a second laptop matters once they are in the picture.
    expect(checkMessage(verdict(seen({ person: "missing", extra: "laptop" })))).toBe(
      "personMissing",
    );
  });
});

describe("whether the screen needs to change", () => {
  it("changes when only the phone's orientation does", () => {
    // Turned sideways with the laptop still cut: the parts are the same, the message isn't.
    expect(sameVerdict(verdict(seen({ portrait: true })), verdict(seen()))).toBe(false);
  });

  it("stays put while nothing it shows changed", () => {
    expect(sameVerdict(verdict(seen()), verdict(seen({ personScore: 0.8 })))).toBe(true);
  });
});
