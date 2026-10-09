import { describe, expect, it } from "vitest";
import {
  cameraResult,
  dbfs,
  microphoneResult,
  peakAmplitude,
  peakDbfs,
  webview2Result,
} from "./thresholds";

describe("dbfs", () => {
  it("is 0 at full scale, either polarity", () => {
    expect(dbfs(1)).toBe(0);
    expect(dbfs(-1)).toBe(0);
  });

  it("is -Infinity for silence", () => {
    expect(dbfs(0)).toBe(Number.NEGATIVE_INFINITY);
  });

  it("halving the amplitude loses about 6 dB", () => {
    expect(dbfs(0.5)).toBeCloseTo(-6.0206, 4);
    expect(dbfs(0.1)).toBeCloseTo(-20, 10);
  });
});

describe("peakDbfs", () => {
  it("uses the largest magnitude in the block", () => {
    expect(peakAmplitude([0.1, -0.5, 0.25])).toBe(0.5);
    expect(peakDbfs(new Float32Array([0.1, -0.5, 0.25]))).toBeCloseTo(-6.0206, 4);
  });

  it("is -Infinity for an all-zero or empty block", () => {
    expect(peakDbfs(new Float32Array(2048))).toBe(Number.NEGATIVE_INFINITY);
    expect(peakDbfs([])).toBe(Number.NEGATIVE_INFINITY);
  });

  it("is 0 for a full-scale block", () => {
    expect(peakDbfs(new Float32Array([0, 1, -1, 0]))).toBe(0);
  });
});

describe("microphoneResult", () => {
  it("passes above -50 dBFS", () => {
    expect(microphoneResult(-18.2)).toEqual({
      check: "microphone",
      status: "pass",
      value: "-18 dBFS peak",
    });
    expect(microphoneResult(-49).status).toBe("pass");
  });

  it("fails at -50 dBFS and below, as shown after rounding", () => {
    expect(microphoneResult(-50).status).toBe("fail");
    expect(microphoneResult(-49.6)).toMatchObject({ status: "fail", value: "-50 dBFS peak" });
    expect(microphoneResult(-72).detail).toBeTruthy();
  });

  it("reports silence without an infinite number", () => {
    const result = microphoneResult(Number.NEGATIVE_INFINITY);
    expect(result.status).toBe("fail");
    expect(result.value).toBe("no sound");
    expect(result.detail).toBeTruthy();
  });

  it("never prints a negative zero", () => {
    expect(microphoneResult(-0.2).value).toBe("0 dBFS peak");
  });
});

describe("cameraResult", () => {
  const camera = { label: "Integrated Webcam", width: 1280, height: 720, frameRate: 30 };

  it("passes at 640x480 and 15 fps", () => {
    expect(cameraResult({ ...camera, width: 640, height: 480, frameRate: 15 }).status).toBe("pass");
  });

  it("names the camera, its size and its frame rate", () => {
    expect(cameraResult({ ...camera, frameRate: 30.00003 })).toEqual({
      check: "camera",
      status: "pass",
      value: "Integrated Webcam 1280x720@30",
    });
    expect(cameraResult({ ...camera, label: "  " }).value).toBe("Camera 1280x720@30");
  });

  it("warns below the minimum width, height or frame rate", () => {
    for (const low of [{ width: 639 }, { height: 479 }, { frameRate: 14.4 }]) {
      const result = cameraResult({ ...camera, width: 640, height: 480, frameRate: 15, ...low });
      expect(result.status, JSON.stringify(low)).toBe("warn");
      expect(result.detail).toContain("640x480");
    }
  });

  it("judges the frame rate as shown, rounded", () => {
    expect(cameraResult({ ...camera, frameRate: 14.6 }).status).toBe("pass");
  });
});

describe("webview2Result", () => {
  it("reads the runtime version from the Edg/ token", () => {
    const userAgent =
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
      "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.2903.86";
    expect(webview2Result(userAgent)).toEqual({
      check: "webview2",
      status: "pass",
      value: "131.0.2903.86",
    });
  });

  it("warns when the version is missing", () => {
    const result = webview2Result("Mozilla/5.0 Chrome/131.0.0.0");
    expect(result.status).toBe("warn");
    expect(result.value).toBe("unknown");
    expect(result.detail).toBeTruthy();
  });
});
