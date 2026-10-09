import { describe, expect, it } from "vitest";
import { buildPayload, DEFAULT_MANDATORY, missingMandatory } from "./payload";
import { CHECK_NAMES, type CheckResult } from "./types";

const native: CheckResult[] = [
  { check: "cpu", status: "pass", value: "8 logical, 23% busy" },
  { check: "memory", status: "pass", value: "6.1 GB free" },
  { check: "disk", status: "pass", value: "41 GB free" },
  { check: "displays", status: "warn", value: "2", detail: "2 displays are connected." },
  { check: "privacy", status: "pass", value: "camera and microphone allowed" },
  { check: "media_foundation", status: "pass", value: "H.264 encoder present (hardware)" },
  { check: "os", status: "pass", value: "Windows 11 26200.6899" },
  { check: "screen_capture", status: "pass", value: "2 displays" },
];

const web: CheckResult[] = [
  { check: "webview2", status: "pass", value: "131.0.2903.86" },
  { check: "speaker", status: "pass", value: "test tone heard" },
  { check: "network", status: "warn", value: "38 ms RTT" },
  { check: "microphone", status: "pass", value: "-18 dBFS peak" },
  { check: "camera", status: "pass", value: "Integrated Webcam 1280x720@30" },
];

describe("buildPayload", () => {
  it("orders the results as the contract lists them", () => {
    const payload = buildPayload({ appVersion: "1.4.0", native, web });
    expect(payload.results.map((result) => result.check)).toEqual([
      "camera",
      "microphone",
      "speaker",
      "screen_capture",
      "network",
      "cpu",
      "memory",
      "disk",
      "displays",
      "privacy",
      "third_eye",
      "media_foundation",
      "webview2",
    ]);
    expect(payload.results.map((result) => result.check)).toEqual([...CHECK_NAMES]);
  });

  it("moves the os check into the payload's os field", () => {
    const payload = buildPayload({ appVersion: "1.4.0", native, web });
    expect(payload.app_version).toBe("1.4.0");
    expect(payload.os).toBe("Windows 11 26200.6899");
    expect(payload.results.some((result) => result.check === "os")).toBe(false);
  });

  it("prefers an explicit os, and says unknown when there is none", () => {
    expect(buildPayload({ appVersion: "1", os: "Windows 11 26200", native, web }).os).toBe(
      "Windows 11 26200",
    );
    expect(buildPayload({ appVersion: "1", native: [], web: [] }).os).toBe("unknown");
  });

  it("adds third_eye as skipped when it is absent", () => {
    const payload = buildPayload({ appVersion: "1", native, web });
    expect(payload.results.find((result) => result.check === "third_eye")).toEqual({
      check: "third_eye",
      status: "skipped",
    });
  });

  it("keeps a third_eye result that is present", () => {
    const paired: CheckResult = { check: "third_eye", status: "pass", value: "paired" };
    const payload = buildPayload({ appVersion: "1", native, web: [...web, paired] });
    expect(payload.results.filter((result) => result.check === "third_eye")).toEqual([paired]);
  });

  it("lets a later web result replace a native one of the same name", () => {
    const retried: CheckResult = { check: "screen_capture", status: "fail", detail: "x" };
    const payload = buildPayload({ appVersion: "1", native, web: [...web, retried] });
    expect(payload.results.filter((result) => result.check === "screen_capture")).toEqual([
      retried,
    ]);
  });

  it("keeps checks the contract doesn't list, after the listed ones", () => {
    const extra: CheckResult = { check: "gpu", status: "pass", value: "UHD 620" };
    const payload = buildPayload({ appVersion: "1", native: [extra, ...native], web });
    expect(payload.results.at(-1)).toEqual(extra);
  });

  it("leaves out checks that never ran, except third_eye", () => {
    const payload = buildPayload({ appVersion: "1", native: [], web: [] });
    expect(payload.results).toEqual([{ check: "third_eye", status: "skipped" }]);
  });

  it("doesn't share result objects with its input", () => {
    const payload = buildPayload({ appVersion: "1", native, web });
    const cpu = payload.results.find((result) => result.check === "cpu");
    expect(cpu).toEqual(native[0]);
    expect(cpu).not.toBe(native[0]);
  });
});

describe("missingMandatory", () => {
  const results: CheckResult[] = [
    { check: "camera", status: "pass" },
    { check: "microphone", status: "fail" },
    { check: "screen_capture", status: "warn" },
  ];

  it("lists mandatory checks that are absent or not a pass, in the policy's order", () => {
    expect(
      missingMandatory(results, ["media_foundation", "camera", "microphone", "screen_capture"]),
    ).toEqual(["media_foundation", "microphone", "screen_capture"]);
  });

  it("is empty when every mandatory check passed", () => {
    expect(missingMandatory(results, ["camera"])).toEqual([]);
    expect(missingMandatory(results, [])).toEqual([]);
  });

  it("judges a repeated check by its later result", () => {
    const retried: CheckResult[] = [
      { check: "camera", status: "fail" },
      { check: "camera", status: "pass" },
      { check: "microphone", status: "pass" },
      { check: "microphone", status: "fail" },
    ];
    expect(missingMandatory(retried, ["camera", "microphone"])).toEqual(["microphone"]);
  });

  it("counts skipped as missing", () => {
    expect(missingMandatory([{ check: "third_eye", status: "skipped" }], ["third_eye"])).toEqual([
      "third_eye",
    ]);
  });

  it("defaults to camera, microphone, screen capture and Media Foundation", () => {
    expect([...DEFAULT_MANDATORY]).toEqual([
      "camera",
      "microphone",
      "screen_capture",
      "media_foundation",
    ]);
    expect(missingMandatory(results)).toEqual(["microphone", "screen_capture", "media_foundation"]);
  });
});
