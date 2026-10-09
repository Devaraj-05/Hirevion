import { describe, expect, it } from "vitest";
import {
  ACCOMMODATIONS,
  applyAccommodations,
  DEFAULT_VISION_CONFIG,
  firstThreshold,
  visionConfigFromPolicy,
} from "./config";
import { CAMERA_SIGNALS } from "./types";

describe("DEFAULT_VISION_CONFIG", () => {
  it("uses the master plan's §6.12 thresholds", () => {
    const { signals } = DEFAULT_VISION_CONFIG;
    expect(signals.FACE_ABSENT).toEqual({ warn_after_ms: 5_000, critical_after_ms: 30_000 });
    expect(signals.MULTIPLE_FACES).toEqual({ critical_after_ms: 3_000 });
    expect(signals.CAMERA_OBSTRUCTED).toEqual({ critical_after_ms: 5_000 });
    expect(signals.FACE_TOO_FAR).toEqual({ warn_after_ms: 10_000 });
    expect(signals.FACE_TOO_CLOSE).toEqual({ warn_after_ms: 10_000 });
  });

  it("has a rule for every camera signal", () => {
    expect(Object.keys(DEFAULT_VISION_CONFIG.signals).sort()).toEqual([...CAMERA_SIGNALS].sort());
  });
});

describe("firstThreshold", () => {
  it("is the warning when there is one, else the critical", () => {
    expect(firstThreshold({ warn_after_ms: 5_000, critical_after_ms: 30_000 })).toEqual({
      ms: 5_000,
      level: "warning",
    });
    expect(firstThreshold({ critical_after_ms: 3_000 })).toEqual({ ms: 3_000, level: "critical" });
  });

  it("is the critical when it comes first", () => {
    expect(firstThreshold({ warn_after_ms: 9_000, critical_after_ms: 4_000 })).toEqual({
      ms: 4_000,
      level: "critical",
    });
  });

  it("is null for a signal with no threshold, which then raises nothing", () => {
    expect(firstThreshold({})).toBeNull();
  });
});

describe("visionConfigFromPolicy", () => {
  it("keeps the defaults for an empty policy", () => {
    expect(visionConfigFromPolicy({})).toEqual(DEFAULT_VISION_CONFIG);
  });

  it("takes the proctor session's thresholds per signal and level", () => {
    const config = visionConfigFromPolicy({
      thresholds: {
        FACE_ABSENT: { warn_after_ms: 8_000, critical_after_ms: 45_000 },
        MULTIPLE_FACES: { critical_after_ms: 2_000 },
      },
    });
    expect(config.signals.FACE_ABSENT).toEqual({ warn_after_ms: 8_000, critical_after_ms: 45_000 });
    expect(config.signals.MULTIPLE_FACES).toEqual({ critical_after_ms: 2_000 });
    expect(config.signals.CAMERA_OBSTRUCTED).toEqual({ critical_after_ms: 5_000 });
  });

  it("merges a partial rule with the default", () => {
    const config = visionConfigFromPolicy({
      thresholds: { FACE_ABSENT: { warn_after_ms: 7_000 } },
    });
    expect(config.signals.FACE_ABSENT).toEqual({ warn_after_ms: 7_000, critical_after_ms: 30_000 });
  });

  it("turns a level off when the policy sends null", () => {
    const config = visionConfigFromPolicy({
      thresholds: { FACE_TOO_FAR: { warn_after_ms: null } },
    });
    expect(config.signals.FACE_TOO_FAR).toEqual({});
  });

  it("ignores unknown signals and values that aren't non-negative numbers", () => {
    const config = visionConfigFromPolicy({
      thresholds: {
        GAZE_DEVIATION: { warn_after_ms: 10_000 },
        FACE_ABSENT: { warn_after_ms: -1, critical_after_ms: "soon" },
        MULTIPLE_FACES: "often",
      },
    });
    expect(config.signals).toEqual(DEFAULT_VISION_CONFIG.signals);
    expect(config.signals).not.toHaveProperty("GAZE_DEVIATION");
  });

  it("never changes the defaults it starts from", () => {
    const before = structuredClone(DEFAULT_VISION_CONFIG);
    visionConfigFromPolicy({
      thresholds: { FACE_ABSENT: { warn_after_ms: 1 } },
      accommodations: ["relaxed_gaze"],
    });
    expect(DEFAULT_VISION_CONFIG).toEqual(before);
  });

  it("applies the session's accommodations after its thresholds", () => {
    const config = visionConfigFromPolicy({
      thresholds: { FACE_TOO_FAR: { warn_after_ms: 6_000 } },
      accommodations: ["relaxed_gaze"],
    });
    expect(config.signals.FACE_TOO_FAR).toEqual({ warn_after_ms: 12_000 });
  });
});

describe("accommodations", () => {
  it("relaxed_gaze relaxes face distance only (master plan §6.4)", () => {
    const relaxed = applyAccommodations(DEFAULT_VISION_CONFIG, ["relaxed_gaze"]);
    expect(relaxed.face.tooFarBelow).toBeLessThan(DEFAULT_VISION_CONFIG.face.tooFarBelow);
    expect(relaxed.face.tooCloseAbove).toBeGreaterThan(DEFAULT_VISION_CONFIG.face.tooCloseAbove);
    expect(relaxed.signals.FACE_TOO_FAR).toEqual({ warn_after_ms: 20_000 });
    expect(relaxed.signals.FACE_TOO_CLOSE).toEqual({ warn_after_ms: 20_000 });
    expect(relaxed.signals.FACE_ABSENT).toEqual(DEFAULT_VISION_CONFIG.signals.FACE_ABSENT);
    expect(relaxed.signals.MULTIPLE_FACES).toEqual(DEFAULT_VISION_CONFIG.signals.MULTIPLE_FACES);
    expect(relaxed.signals.CAMERA_OBSTRUCTED).toEqual(
      DEFAULT_VISION_CONFIG.signals.CAMERA_OBSTRUCTED,
    );
  });

  it("ignores kinds that don't concern the camera, so new kinds need no caller change", () => {
    expect(
      applyAccommodations(DEFAULT_VISION_CONFIG, ["extended_time", "breaks", "made_up"]),
    ).toEqual(DEFAULT_VISION_CONFIG);
  });

  it("applies a kind once even when it is listed twice", () => {
    expect(applyAccommodations(DEFAULT_VISION_CONFIG, ["relaxed_gaze", "relaxed_gaze"])).toEqual(
      applyAccommodations(DEFAULT_VISION_CONFIG, ["relaxed_gaze"]),
    );
  });

  it("is a registry keyed by the contract's kinds", () => {
    expect(Object.keys(ACCOMMODATIONS)).toContain("relaxed_gaze");
  });
});
