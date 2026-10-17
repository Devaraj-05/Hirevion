import { describe, expect, it } from "vitest";
import { readToken, recallDevice, rememberDevice, wantsAutoStart } from "./token";

describe("readToken", () => {
  it("reads the pairing token from the URL fragment", () => {
    expect(readToken("#t=abc.def-ghi_jkl")).toBe("abc.def-ghi_jkl");
  });

  it("decodes escaped characters", () => {
    expect(readToken("#t=a%2Bb%2Fc%3D")).toBe("a+b/c=");
  });

  it("returns null when there is no token", () => {
    for (const hash of ["", "#", "#t=", "#x=1"]) {
      expect(readToken(hash)).toBeNull();
    }
  });
});

describe("wantsAutoStart", () => {
  it("is true only for auto=1 in the fragment (automated tests)", () => {
    expect(wantsAutoStart("#t=abc&auto=1")).toBe(true);
    expect(wantsAutoStart("#t=abc")).toBe(false);
    expect(wantsAutoStart("#t=abc&auto=yes")).toBe(false);
  });
});

describe("the device secret", () => {
  it("is kept for the tab, and missing storage is no error", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value),
    } as unknown as Storage;
    rememberDevice(storage, "secret");
    expect(recallDevice(storage)).toBe("secret");
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(() => rememberDevice(broken, "secret")).not.toThrow();
    expect(recallDevice(broken)).toBeNull();
    expect(recallDevice(undefined)).toBeNull();
  });
});
