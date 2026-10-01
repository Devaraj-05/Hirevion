"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { writePreference } from "@/shell/preferences";
import { LOCALE_COOKIE, resolveLocale } from "./locales";

/** Stores the language choice and re-renders the page in it (the URL doesn't change). */
export function useSetLocale(): (locale: string) => void {
  const router = useRouter();
  return useCallback(
    (value: string) => {
      writePreference(LOCALE_COOKIE, resolveLocale(value));
      router.refresh();
    },
    [router],
  );
}
