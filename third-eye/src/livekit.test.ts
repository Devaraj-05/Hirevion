import { Track, VideoPresets } from "livekit-client";
import { describe, expect, it } from "vitest";
import { CAMERA_PUBLISH } from "./livekit";

describe("the phone's camera in the room", () => {
  it("sends a small simulcast layer for the candidate's side tile (C8-12)", () => {
    // The recorder and the vision agent take the full 720p layer; the laptop asks for the
    // 180p one, so it downloads a few hundred kbps instead of 1.2 Mbps.
    expect(CAMERA_PUBLISH.simulcast).toBe(true);
    expect(CAMERA_PUBLISH.videoSimulcastLayers).toEqual([VideoPresets.h180]);
    expect(CAMERA_PUBLISH.videoEncoding).toEqual({ maxBitrate: 1_200_000, maxFramerate: 15 });
    expect(CAMERA_PUBLISH.source).toBe(Track.Source.Camera);
  });
});
