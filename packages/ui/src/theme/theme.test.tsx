import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, themeScript, useTheme } from "./theme";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useTheme", () => {
  it("defaults to the system preference and applies light without a dark preference", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("system");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("remembers the choice and applies it", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("dark"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    const again = renderHook(() => useTheme());
    expect(again.result.current.preference).toBe("dark");
  });

  it("still works when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("dark"));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("themeScript", () => {
  it("applies the stored theme before React loads", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(themeScript())();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
