import { describe, expect, it } from "vitest";
import type { UploadProgress } from "../native/commands";
import { uploadView } from "./upload";

const base: UploadProgress = {
  pending: 0,
  pending_bytes: 0,
  acknowledged: 12,
  lost: 0,
  rejected: 0,
  percent: 100,
  recording: false,
  done: true,
};

describe("the upload-drain view", () => {
  it("checks until Rust has answered", () => {
    expect(uploadView(null)).toEqual({ state: "checking" });
  });

  it("says it is safe only when Rust says done and nothing is pending", () => {
    expect(uploadView(base)).toEqual({ state: "done", gaps: 0 });
    expect(uploadView({ ...base, done: false })).toMatchObject({ state: "uploading" });
    expect(uploadView({ ...base, pending: 2 })).toMatchObject({ state: "uploading", pending: 2 });
    expect(uploadView({ ...base, recording: true })).toMatchObject({ state: "uploading" });
  });

  it("never shows 100 percent while uploading", () => {
    const view = uploadView({ ...base, done: false, pending: 1, percent: 100 });
    expect(view).toEqual({ state: "uploading", percent: 99, pending: 1 });
  });

  it("clamps what it shows", () => {
    expect(uploadView({ ...base, done: false, pending: 3, percent: -4 })).toMatchObject({
      percent: 0,
    });
    expect(uploadView({ ...base, done: false, pending: 3, percent: 41.9 })).toMatchObject({
      percent: 41,
    });
  });

  it("reports parts that could never be uploaded", () => {
    expect(uploadView({ ...base, lost: 2, rejected: 1 })).toEqual({ state: "done", gaps: 3 });
  });
});
