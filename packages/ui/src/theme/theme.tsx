"use client";

import { useCallback, useEffect, useState } from "react";
import { DARK_QUERY, THEME_STORAGE_KEY, type ThemePreference } from "./theme-script";

export { THEME_STORAGE_KEY, type ThemePreference, ThemeScript, themeScript } from "./theme-script";

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

/** Tells every mounted useTheme() about a choice made through any one of them. */
const CHANGE_EVENT = "hv-theme-change";

function apply(preference: ThemePreference): void {
  const dark =
    preference === "dark" || (preference === "system" && window.matchMedia(DARK_QUERY).matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function useTheme(): {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
} {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    const onChange = (event: Event) => {
      setPreferenceState((event as CustomEvent<ThemePreference>).detail);
    };
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => window.removeEventListener(CHANGE_EVENT, onChange);
  }, []);

  useEffect(() => {
    apply(preference);
    if (preference !== "system") return;
    const query = window.matchMedia(DARK_QUERY);
    const onChange = () => apply("system");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private mode or blocked storage: the choice lasts for this page only.
    }
    apply(next);
    setPreferenceState(next);
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: next }));
  }, []);

  return { preference, setPreference };
}
