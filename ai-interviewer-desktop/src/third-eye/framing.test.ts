import { describe, expect, it } from "vitest";
import { type Detection, framing, Steady, toScreen } from "./framing";

// A 1280×720 picture from the phone, beside the candidate.
const W = 1280;
const H = 720;
const person = (x: number, y: number, width: number, height: number, score = 0.9): Detection => ({
  label: "person",
  score,
  box: { x, y, width, height },
});
const laptop = (x: number, y: number, width: number, height: number, score = 0.7): Detection => ({
  label: "laptop",
  score,
  box: { x, y, width, height },
});

describe("whether the phone's picture shows the candidate and their whole laptop", () => {
  it("is green with both well inside the picture", () => {
    const seen = framing([person(500, 60, 400, 660), laptop(150, 380, 380, 220)], W, H);
    expect(seen).toMatchObject({ person: "ok", laptop: "ok", green: true });
    expect(seen.personScore).toBeCloseTo(0.9);
    expect(seen.laptopScore).toBeCloseTo(0.7);
  });

  it("names what is missing", () => {
    expect(framing([], W, H)).toMatchObject({ person: "missing", laptop: "missing", green: false });
    expect(framing([person(500, 60, 400, 660)], W, H)).toMatchObject({
      person: "ok",
      laptop: "missing",
      green: false,
    });
    expect(framing([laptop(150, 380, 380, 220)], W, H)).toMatchObject({ person: "missing" });
  });

  it("accepts a keyboard for the laptop, and ignores weak guesses", () => {
    const keyboard: Detection = {
      label: "keyboard",
      score: 0.6,
      box: { x: 200, y: 450, width: 300, height: 120 },
    };
    expect(framing([person(500, 60, 400, 660), keyboard], W, H).laptop).toBe("ok");
    const unsure = framing([person(500, 60, 400, 660, 0.3), laptop(150, 380, 380, 220, 0.2)], W, H);
    expect(unsure).toMatchObject({ person: "missing", laptop: "missing" });
  });

  it("judges the whole laptop when it sees one, not just its keyboard", () => {
    const keyboard: Detection = {
      label: "keyboard",
      score: 0.7,
      box: { x: 200, y: 450, width: 300, height: 120 },
    };
    // The lid runs off the top while the keyboard is inside: the laptop isn't wholly in view.
    const lidCut = laptop(150, 0, 380, 600, 0.55);
    expect(framing([person(500, 60, 400, 660), lidCut, keyboard], W, H).laptop).toBe("cut");
  });

  it("isn't green when the laptop runs off an edge", () => {
    // The keyboard's front edge is cut by the bottom of the picture.
    const cut = framing([person(500, 60, 400, 660), laptop(150, 500, 380, 220)], W, H);
    expect(cut).toMatchObject({ laptop: "cut", green: false });
    const left = framing([person(500, 60, 400, 660), laptop(0, 380, 380, 220)], W, H);
    expect(left.laptop).toBe("cut");
  });

  it("isn't green when the candidate's head or side is cut off, but their legs may be", () => {
    expect(framing([person(500, 0, 400, 700), laptop(150, 380, 380, 220)], W, H).person).toBe(
      "cut",
    );
    expect(framing([person(1000, 60, 280, 660), laptop(150, 380, 380, 220)], W, H).person).toBe(
      "cut",
    );
    // Sitting at a desk, the bottom of the person's box reaches the bottom of the picture.
    expect(framing([person(500, 60, 400, 660), laptop(150, 380, 380, 220)], W, H).person).toBe(
      "ok",
    );
  });

  it("takes the best of each when the detector sees several", () => {
    const seen = framing(
      [person(500, 60, 400, 660, 0.6), person(520, 70, 390, 650, 0.95), laptop(150, 380, 380, 220)],
      W,
      H,
    );
    expect(seen.personScore).toBeCloseTo(0.95);
  });
});

describe("drawing a box over the preview", () => {
  it("maps a box from the picture onto the letterboxed video element", () => {
    // A 1280×720 picture in an 800×600 element: scaled by 0.625, with 75 px bands above and below.
    expect(
      toScreen(
        { x: 128, y: 72, width: 640, height: 360 },
        { width: 1280, height: 720 },
        { width: 800, height: 600 },
      ),
    ).toEqual({ x: 80, y: 120, width: 400, height: 225 });
    // A portrait picture in a wide element: bands on the sides.
    expect(
      toScreen(
        { x: 0, y: 0, width: 720, height: 1280 },
        { width: 720, height: 1280 },
        { width: 1000, height: 640 },
      ),
    ).toEqual({ x: 320, y: 0, width: 360, height: 640 });
  });
});

describe("holding the green", () => {
  it("turns green after 3 s of green pictures, and back after 1 s without", () => {
    const steady = new Steady(3_000, 1_000);
    expect(steady.update(true, 0)).toBe(false);
    expect(steady.update(true, 2_900)).toBe(false);
    expect(steady.update(true, 3_000)).toBe(true);
    // A single missed picture doesn't drop it.
    expect(steady.update(false, 3_500)).toBe(true);
    expect(steady.update(true, 3_800)).toBe(true);
    expect(steady.update(false, 4_000)).toBe(true);
    expect(steady.update(false, 5_000)).toBe(false);
    // Green again needs another 3 s.
    expect(steady.update(true, 5_100)).toBe(false);
    expect(steady.update(true, 8_100)).toBe(true);
  });
});
