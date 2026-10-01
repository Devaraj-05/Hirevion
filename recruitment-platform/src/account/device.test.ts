import { describe, expect, it } from "vitest";
import { describeDevice } from "./device";

describe("describeDevice", () => {
  it("names the browser and the system", () => {
    expect(
      describeDevice(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36 Edg/141.0",
      ),
    ).toEqual({ browser: "Edge", system: "Windows" });
    expect(
      describeDevice(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Safari/605.1.15",
      ),
    ).toEqual({ browser: "Safari", system: "macOS" });
    expect(
      describeDevice("Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"),
    ).toEqual({ browser: "Firefox", system: "Linux" });
    expect(
      describeDevice(
        "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Mobile Safari/537.36",
      ),
    ).toEqual({ browser: "Chrome", system: "Android" });
    expect(
      describeDevice(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1",
      ),
    ).toEqual({ browser: "Safari", system: "iOS" });
  });

  it("admits when it can't tell", () => {
    expect(describeDevice(null)).toBeNull();
    expect(describeDevice("curl/8.9")).toBeNull();
  });
});
