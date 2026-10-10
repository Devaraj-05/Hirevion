import { describe, expect, it } from "vitest";
import {
  CAMERA_H264,
  CAMERA_VP8,
  chooseCameraFormat,
  chooseRecorderFormat,
  isAllowed,
  MIC_OPUS,
} from "./formats";

describe("formats", () => {
  it("follows the recordings contract", () => {
    expect(isAllowed("camera", "mp4", "h264")).toBe(true);
    expect(isAllowed("camera", "webm", "vp8")).toBe(true);
    expect(isAllowed("camera", "webm", "opus")).toBe(false);
    expect(isAllowed("mic", "webm", "opus")).toBe(true);
    expect(isAllowed("mic", "mp4", "aac")).toBe(true);
    expect(isAllowed("mic", "mp4", "opus")).toBe(false);
    for (const format of [CAMERA_H264, CAMERA_VP8]) {
      expect(isAllowed("camera", format.container, format.codec)).toBe(true);
    }
    expect(isAllowed("mic", MIC_OPUS.container, MIC_OPUS.codec)).toBe(true);
  });

  it("records the camera as H.264 MP4 when it can, VP8 WebM otherwise", () => {
    expect(chooseCameraFormat(true)).toBe(CAMERA_H264);
    expect(chooseCameraFormat(false)).toBe(CAMERA_VP8);
  });

  it("picks a MediaRecorder type the contract accepts", () => {
    const only = (supported: string[]) => (type: string) => supported.includes(type);
    expect(chooseRecorderFormat("camera", only(["video/webm;codecs=vp8"]))).toMatchObject({
      container: "webm",
      codec: "vp8",
      recorderMime: "video/webm;codecs=vp8",
    });
    expect(chooseRecorderFormat("camera", only(["video/mp4;codecs=avc1"]))).toMatchObject({
      container: "mp4",
      codec: "h264",
    });
    expect(chooseRecorderFormat("mic", only(["audio/webm;codecs=opus"]))).toMatchObject({
      container: "webm",
      codec: "opus",
    });
    expect(chooseRecorderFormat("mic", only(["audio/mp4;codecs=mp4a.40.2"]))).toMatchObject({
      container: "mp4",
      codec: "aac",
    });
    // H.264 in WebM isn't in the contract.
    expect(chooseRecorderFormat("camera", only(["video/webm;codecs=h264"]))).toBeNull();
  });
});
