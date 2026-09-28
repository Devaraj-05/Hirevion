import { describe, expect, it } from "vitest";
import { parseRoute } from "./routes";

describe("parseRoute", () => {
  it("reads the route and its query parameters", () => {
    const { route, params } = parseRoute("#/media?auto=60");
    expect(route).toBe("media");
    expect(params.get("auto")).toBe("60");
  });

  it("falls back to home for empty or unknown hashes", () => {
    expect(parseRoute("").route).toBe("home");
    expect(parseRoute("#/").route).toBe("home");
    expect(parseRoute("#/nope?auto=1").route).toBe("home");
  });

  it("keeps question marks inside parameter values", () => {
    expect(parseRoute("#/livekit?url=wss://x/?a=1").params.get("url")).toBe("wss://x/?a=1");
  });
});
