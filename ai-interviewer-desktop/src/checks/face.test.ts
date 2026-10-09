import { describe, expect, it } from "vitest";
import enIN from "../i18n/en-IN.json";
import enUS from "../i18n/en-US.json";
import { CAMERA_SIGNALS, type FaceBox, type FaceObservation, type FrameStats } from "../vision";
import {
  assessFace,
  BLOCKING_FACE_ISSUES,
  cameraWithFaceGuidance,
  FACE_ISSUES,
  type FaceGuidance,
  faceGuidanceText,
} from "./face";
import type { CheckResult } from "./types";

const LIT: FrameStats = { meanLuma: 0.45, stdLuma: 0.2, edgeEnergy: 0.08 };
const DIM: FrameStats = { meanLuma: 0.15, stdLuma: 0.1, edgeEnergy: 0.05 };
const BLACK: FrameStats = { meanLuma: 0.01, stdLuma: 0.005, edgeEnergy: 0.001 };

/** A face whose box is centred on (cx, cy). */
function face(height: number, cx = 0.5, cy = 0.45, score = 0.9): FaceBox {
  const width = height * 0.75;
  return { x: cx - width / 2, y: cy - height / 2, width, height, score };
}

function frames(count: number, faces: FaceBox[], frame: FrameStats | null = LIT) {
  return Array.from(
    { length: count },
    (_, index): FaceObservation => ({
      t: index * 100,
      faces,
      frame,
    }),
  );
}

const issues = (observations: FaceObservation[]) => assessFace(observations).issues;

describe("assessFace", () => {
  it("finds nothing wrong with one well-lit, centred face at a normal distance", () => {
    expect(assessFace(frames(20, [face(0.35)]))).toEqual({ issues: [], frames: 20 });
  });

  it("asks for a face when there is none", () => {
    expect(issues(frames(20, []))).toEqual(["no_face"]);
  });

  it("says the camera is covered rather than that the face is missing", () => {
    expect(issues(frames(20, [], BLACK))).toEqual(["obstructed"]);
  });

  it("asks for the candidate to be alone", () => {
    expect(issues(frames(20, [face(0.35), face(0.25, 0.15)]))).toEqual(["multiple_faces"]);
  });

  it("asks for more light on a dim frame, even with the face found", () => {
    expect(issues(frames(20, [face(0.35)], DIM))).toEqual(["too_dark"]);
  });

  it("asks the candidate to come closer or move back", () => {
    expect(issues(frames(20, [face(0.1)]))).toEqual(["too_far"]);
    expect(issues(frames(20, [face(0.75, 0.5, 0.5)]))).toEqual(["too_close"]);
  });

  it("asks the candidate to move to the middle of the picture", () => {
    expect(issues(frames(20, [face(0.35, 0.85)]))).toEqual(["off_centre"]);
    expect(issues(frames(20, [face(0.35, 0.6)]))).toEqual([]);
  });

  it("lists several issues in priority order", () => {
    expect(issues(frames(20, [face(0.1, 0.9)], DIM))).toEqual([
      "too_dark",
      "too_far",
      "off_centre",
    ]);
  });

  it("reports an issue only when most frames show it", () => {
    const mostlyFine = [...frames(16, [face(0.35)]), ...frames(4, [])];
    expect(issues(mostlyFine)).toEqual([]);
    const mostlyEmpty = [...frames(8, [face(0.35)]), ...frames(12, [])];
    expect(issues(mostlyEmpty)).toEqual(["no_face"]);
  });

  it("says guidance is unavailable with too few frames", () => {
    expect(assessFace([])).toEqual({ issues: ["unavailable"], frames: 0 });
    expect(issues(frames(2, [face(0.35)]))).toEqual(["unavailable"]);
  });
});

describe("faceGuidanceText", () => {
  it("has a message for every issue in both languages", () => {
    for (const catalogue of [enIN, enUS]) {
      const guidance = catalogue.vision.guidance as Record<string, string>;
      for (const issue of FACE_ISSUES) expect(guidance[issue]).toBeTruthy();
    }
  });

  it("has a nudge for every camera signal in both languages", () => {
    for (const catalogue of [enIN, enUS]) {
      const nudges = catalogue.vision.nudges as Record<string, string>;
      for (const signal of CAMERA_SIGNALS) expect(nudges[signal]).toBeTruthy();
    }
  });

  it("reads the en-IN message by default", () => {
    expect(faceGuidanceText("no_face")).toBe(enIN.vision.guidance.no_face);
  });
});

describe("cameraWithFaceGuidance", () => {
  const camera: CheckResult = {
    check: "camera",
    status: "pass",
    value: "Integrated Webcam 1280x720@30",
  };
  const guidance = (...found: FaceGuidance["issues"]): FaceGuidance => ({
    issues: found,
    frames: 20,
  });

  it("leaves a passing camera alone when the face is fine", () => {
    expect(cameraWithFaceGuidance(camera, guidance())).toEqual(camera);
  });

  it("keeps the camera check's name, so the upload's check names don't change", () => {
    expect(cameraWithFaceGuidance(camera, guidance("no_face")).check).toBe("camera");
  });

  it("turns a pass into a warning when the face can't be proctored, with what to do", () => {
    for (const issue of BLOCKING_FACE_ISSUES) {
      const result = cameraWithFaceGuidance(camera, guidance(issue));
      expect(result).toEqual({ ...camera, status: "warn", detail: faceGuidanceText(issue) });
    }
  });

  it("only advises on lighting, distance and centring", () => {
    expect(cameraWithFaceGuidance(camera, guidance("too_dark", "off_centre"))).toEqual({
      ...camera,
      detail: `${faceGuidanceText("too_dark")} ${faceGuidanceText("off_centre")}`,
    });
  });

  it("lets a policy make every issue advisory", () => {
    expect(cameraWithFaceGuidance(camera, guidance("no_face"), { blocking: [] }).status).toBe(
      "pass",
    );
  });

  it("adds the guidance after an existing warning's detail", () => {
    const slow: CheckResult = { ...camera, status: "warn", detail: "The camera gives 10 fps." };
    expect(cameraWithFaceGuidance(slow, guidance("too_far"))).toEqual({
      ...slow,
      detail: `The camera gives 10 fps. ${faceGuidanceText("too_far")}`,
    });
  });

  it("leaves a failed or skipped camera, and unavailable guidance, alone", () => {
    const failed: CheckResult = { check: "camera", status: "fail", detail: "No camera found." };
    expect(cameraWithFaceGuidance(failed, guidance("no_face"))).toEqual(failed);
    expect(cameraWithFaceGuidance(camera, guidance("unavailable"))).toEqual(camera);
  });

  it("uses the screen's translator when given one", () => {
    const result = cameraWithFaceGuidance(camera, guidance("too_far"), {
      describe: (issue) => `[${issue}]`,
    });
    expect(result.detail).toBe("[too_far]");
  });
});
