import { describe, expect, it } from "vitest";
import { readCookie } from "./cookies";

describe("readCookie", () => {
  it("finds a cookie by name among the others", () => {
    const jar = "hv_locale=en-IN; __Host-hv_csrf=abc-DEF_123; hv_sidebar=collapsed";
    expect(readCookie("__Host-hv_csrf", jar)).toBe("abc-DEF_123");
    expect(readCookie("hv_sidebar", jar)).toBe("collapsed");
  });

  it("keeps an equals sign inside the value", () => {
    expect(readCookie("token", "token=a=b")).toBe("a=b");
  });

  it("returns undefined for a missing cookie", () => {
    expect(readCookie("__Host-hv_csrf", "hv_locale=en-IN")).toBeUndefined();
    expect(readCookie("__Host-hv_csrf", "")).toBeUndefined();
  });
});
