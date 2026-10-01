"use client";

import { useEffect, useRef } from "react";
import type { RoutePath } from "@/auth/manifest";
import { SHORTCUTS } from "./nav";

const SEQUENCE_MS = 1_000;

export interface ShortcutOptions {
  navigate: (path: RoutePath) => void;
  onPalette: () => void;
  /** Whether the session may open a shortcut's section. */
  allowed: (path: RoutePath) => boolean;
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || target.matches("input, textarea, select, [role='textbox']");
}

/** Ctrl/⌘+K opens the palette anywhere; `g` then a letter goes to a section, except while typing. */
export function useShortcuts(options: ShortcutOptions): void {
  const latest = useRef(options);
  useEffect(() => {
    latest.current = options;
  });

  useEffect(() => {
    let pendingSince = Number.NEGATIVE_INFINITY;

    function onKeyDown(event: KeyboardEvent) {
      const { navigate, onPalette, allowed } = latest.current;
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && !event.altKey && key === "k") {
        event.preventDefault();
        onPalette();
        return;
      }
      if (
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        event.defaultPrevented ||
        isTyping(event.target)
      ) {
        pendingSince = Number.NEGATIVE_INFINITY;
        return;
      }
      if (Date.now() - pendingSince < SEQUENCE_MS) {
        pendingSince = Number.NEGATIVE_INFINITY;
        const path = SHORTCUTS[key as keyof typeof SHORTCUTS];
        if (path && allowed(path)) {
          event.preventDefault();
          navigate(path);
        }
        return;
      }
      if (key === "g") pendingSince = Date.now();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
