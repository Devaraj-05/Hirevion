"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

const KNOWN = new Set([
  "too_short",
  "too_long",
  "personal",
  "breached",
  "wrong_current",
  "wrong_password",
]);

/** The message for a password problem code from the API (or the client's own length check). */
export function usePasswordProblem(): (code: string) => string {
  const t = useTranslations("auth.problems");
  return useCallback(
    (code: string) => (KNOWN.has(code) ? t(code as "too_short") : t("unknown")),
    [t],
  );
}
