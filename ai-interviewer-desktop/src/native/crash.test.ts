import { describe, expect, it } from "vitest";
import { describeError, installCrashReporting, type WebviewError } from "./crash";

describe("describing an error", () => {
  it("keeps an Error's name, message and stack", () => {
    const error = new TypeError("x is undefined");
    const described = describeError("error", error);
    expect(described.message).toBe("TypeError: x is undefined");
    expect(described.stack).toContain("TypeError");
    expect(described.kind).toBe("error");
  });

  it("takes strings and other values as the message", () => {
    expect(describeError("unhandledrejection", "boom").message).toBe("boom");
    expect(describeError("error", { code: 7 }).message).toBe('{"code":7}');
    expect(describeError("error", undefined).message).toBe("undefined");
    expect(describeError("error", "boom").stack).toBeNull();
  });

  it("bounds what it sends", () => {
    const error = new Error("m".repeat(10_000));
    error.stack = "s".repeat(50_000);
    const described = describeError("error", error);
    expect(described.message.length).toBe(2_000);
    expect(described.stack?.length).toBe(6_000);
  });
});

describe("installing", () => {
  it("reports uncaught errors and rejections, and survives a failing report", async () => {
    const listeners = new Map<string, (event: unknown) => void>();
    const sent: WebviewError[] = [];
    installCrashReporting(
      {
        addEventListener: (type: string, listener: unknown) =>
          listeners.set(type, listener as (event: unknown) => void),
      } as Pick<Window, "addEventListener">,
      async (error) => {
        sent.push(error);
        throw new Error("the command failed");
      },
    );
    listeners.get("error")?.({ error: new Error("render failed"), message: "ignored" });
    listeners.get("error")?.({ message: "Script error." });
    listeners.get("unhandledrejection")?.({ reason: "nope" });
    await Promise.resolve();
    expect(sent.map((error) => [error.kind, error.message])).toEqual([
      ["error", "Error: render failed"],
      ["error", "Script error."],
      ["unhandledrejection", "nope"],
    ]);
  });
});
