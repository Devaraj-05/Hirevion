import { describe, expect, it } from "vitest";
import { assertSafeEnvironment, devToolsEnabled } from "./environment";

describe("development tools", () => {
  it("are on only when asked for", () => {
    expect(devToolsEnabled({ HV_WEB_DEV_TOOLS: "true" })).toBe(true);
    expect(devToolsEnabled({ HV_WEB_DEV_TOOLS: "false" })).toBe(false);
    expect(devToolsEnabled({})).toBe(false);
  });

  it("default to on under next dev, unless switched off", () => {
    expect(devToolsEnabled({ NODE_ENV: "development" })).toBe(true);
    expect(devToolsEnabled({ NODE_ENV: "development", HV_WEB_DEV_TOOLS: "false" })).toBe(false);
    expect(devToolsEnabled({ NODE_ENV: "production" })).toBe(false);
    expect(devToolsEnabled({ NODE_ENV: "test" })).toBe(false);
  });

  it("can't start in production even by default", () => {
    expect(() =>
      assertSafeEnvironment({ NODE_ENV: "development", HV_ENVIRONMENT: "production" }),
    ).toThrow(/production/);
  });

  it("can never run in production", () => {
    expect(() =>
      assertSafeEnvironment({ HV_WEB_DEV_TOOLS: "true", HV_ENVIRONMENT: "production" }),
    ).toThrow(/production/);
    expect(() => assertSafeEnvironment({ HV_WEB_DEV_TOOLS: "true" })).not.toThrow();
    expect(() => assertSafeEnvironment({ HV_ENVIRONMENT: "production" })).not.toThrow();
  });
});
