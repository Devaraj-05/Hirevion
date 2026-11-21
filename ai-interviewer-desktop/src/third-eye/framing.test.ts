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

  it("counts the candidate when seen, even sitting close enough to reach the picture's edges", () => {
    // A candidate near the phone fills the picture: their box touches the top and a side.
    expect(framing([person(500, 0, 780, 720), laptop(150, 380, 380, 220)], W, H).person).toBe("ok");
    expect(framing([person(1000, 60, 280, 660), laptop(150, 380, 380, 220)], W, H).person).toBe(
      "ok",
    );
  });

  it("reads the owner's real picture as it is: them clearly, the laptop cut at the left edge", () => {
    // EfficientDet-Lite2 on the product owner's first landscape preview (2026-11-16, 693×390).
    const seen = framing(
      [person(86, 3, 618, 382, 0.93), laptop(0, 239, 345, 146, 0.609)],
      693,
      390,
    );
    expect(seen).toMatchObject({ person: "ok", laptop: "cut", green: false });
    // The phone moved back so the whole laptop fits: green.
    const moved = framing(
      [person(260, 20, 380, 360, 0.9), laptop(30, 200, 280, 150, 0.7)],
      693,
      390,
    );
    expect(moved).toMatchObject({ person: "ok", laptop: "ok", green: true });
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

describe("someone or something else in the picture (owner, 2026-11-16)", () => {
  it("finds a second laptop and isn't green, even with the candidate's own laptop in full view", () => {
    // EfficientDet-Lite2 on the owner's picture with a second laptop at the left (693×390).
    const seen = framing(
      [
        person(194, 57, 380, 328, 0.9),
        laptop(0, 268, 187, 118, 0.41),
        laptop(183, 254, 103, 55, 0.33),
      ],
      693,
      390,
    );
    expect(seen.extra).toBe("laptop");
    expect(seen.green).toBe(false);
    expect(seen.others).toHaveLength(1);
  });

  it("judges the laptop beside the candidate, not the one scored highest", () => {
    const seen = framing(
      [
        person(500, 60, 400, 660),
        laptop(560, 420, 300, 180, 0.5), // in front of the candidate
        laptop(20, 300, 260, 200, 0.8), // across the room
      ],
      W,
      H,
    );
    expect(seen.laptopBox).toMatchObject({ x: 560 });
    expect(seen.laptopScore).toBeCloseTo(0.5);
    expect(seen.others).toEqual([{ x: 20, y: 300, width: 260, height: 200 }]);
  });

  it("never takes the candidate's own faint laptop for another one", () => {
    const seen = framing([person(500, 60, 400, 660), laptop(560, 420, 300, 180, 0.35)], W, H);
    expect(seen).toMatchObject({ extra: null, laptop: "missing", green: false });
  });

  it("finds a second person standing right behind the candidate", () => {
    // A candidate near the phone fills the picture; the helper's centre falls inside their box.
    const seen = framing(
      [person(300, 0, 900, 720), person(700, 40, 260, 500, 0.8), laptop(150, 380, 380, 220)],
      W,
      H,
    );
    expect(seen).toMatchObject({ extra: "person", green: false });
  });

  it("finds a second person", () => {
    const seen = framing(
      [person(500, 60, 400, 660), person(40, 120, 220, 560, 0.7), laptop(150, 380, 380, 220)],
      W,
      H,
    );
    expect(seen).toMatchObject({ extra: "person", green: false });
  });

  it("doesn't count one laptop seen twice, or its keyboard, as another", () => {
    const keyboard: Detection = {
      label: "keyboard",
      score: 0.5,
      box: { x: 200, y: 470, width: 280, height: 110 },
    };
    const seen = framing(
      [
        person(500, 60, 400, 660),
        laptop(150, 380, 380, 220, 0.7),
        laptop(160, 400, 360, 190, 0.35),
        keyboard,
      ],
      W,
      H,
    );
    expect(seen).toMatchObject({ extra: null, green: true, others: [] });
  });

  it("ignores faint guesses and tiny far-off people", () => {
    const seen = framing(
      [
        person(500, 60, 400, 660),
        laptop(150, 380, 380, 220),
        laptop(900, 40, 200, 120, 0.2),
        person(1200, 10, 30, 60, 0.6), // a poster on the wall: under 2% of the picture
      ],
      W,
      H,
    );
    expect(seen).toMatchObject({ extra: null, green: true });
  });
});

describe("the phone's orientation", () => {
  it("is never green with an upright phone's tall picture, and says to turn it", () => {
    // A 720×1280 picture: the phone stands upright, so the laptop and the candidate can't both fit.
    const tall = framing([person(200, 100, 400, 1180), laptop(100, 700, 500, 300)], 720, 1280);
    expect(tall).toMatchObject({ portrait: true, green: false });
    expect(framing([], 1280, 720).portrait).toBe(false);
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
