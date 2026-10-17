import { describe, expect, it } from "vitest";
import { cameraHelp, detectBrowser } from "./guidance";

const IOS_SAFARI_17 =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
const IOS_SAFARI_16_2 =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.2 Mobile/15E148 Safari/604.1";
const IOS_CHROME =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1";
const ANDROID_CHROME =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36";
const ANDROID_SAMSUNG =
  "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36";

describe("detectBrowser", () => {
  it.each([
    [IOS_SAFARI_17, "ios-safari", true],
    [IOS_SAFARI_16_2, "ios-safari", false],
    [IOS_CHROME, "ios-other", true],
    [ANDROID_CHROME, "android-chrome", true],
    [ANDROID_SAMSUNG, "android-other", true],
    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "other", true],
  ])("reads %s", (agent, kind, supported) => {
    const found = detectBrowser(agent);
    expect(found.kind).toBe(kind);
    expect(found.supported).toBe(supported);
  });
});

describe("cameraHelp", () => {
  it("tells iOS Safari users where the camera setting is after a refusal", () => {
    const help = cameraHelp(detectBrowser(IOS_SAFARI_17), "denied");
    expect(help.join(" ")).toMatch(/aA|Website Settings/);
    expect(help.join(" ")).toMatch(/Camera/);
  });

  it("tells Android Chrome users to use the lock icon", () => {
    const help = cameraHelp(detectBrowser(ANDROID_CHROME), "denied");
    expect(help.join(" ")).toMatch(/lock|Permissions/);
  });

  it("asks before the prompt, and warns old iOS versions", () => {
    expect(cameraHelp(detectBrowser(ANDROID_CHROME), "prompt").join(" ")).toMatch(/Allow/);
    expect(cameraHelp(detectBrowser(IOS_SAFARI_16_2), "prompt").join(" ")).toMatch(/16\.4/);
  });
});
