import { describe, expect, it } from "vitest";
import { assertSafeEnvironment, devToolsEnabled } from "./environment";

describe("development tools", () => {
  it("are on only when asked for", () => {
    expect(devToolsEnabled({ HV_WEB_DEV_TOOLS: "true" })).toBe(true);
    expect(devToolsEnabled({ HV_WEB_DEV_TOOLS: "false" })).toBe(false);
    expect(devToolsEnabled({})).toBe(false);
  });

  it("can never run in production", () => {
    expect(() =>
      assertSafeEnvironment({ HV_WEB_DEV_TOOLS: "true", HV_ENVIRONMENT: "production" }),
    ).toThrow(/production/);
    expect(() => assertSafeEnvironment({ HV_WEB_DEV_TOOLS: "true" })).not.toThrow();
    expect(() => assertSafeEnvironment({ HV_ENVIRONMENT: "production" })).not.toThrow();
  });
});
