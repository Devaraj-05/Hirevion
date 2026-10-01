"use client";

import { type ApiProblem, isApiProblem } from "@hirevion/api-client";
import { toast } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useCallback } from "react";

/** Shows a failed call as a toast naming the problem and the trace id to quote to support. */
export function useProblemToast(): (error: unknown) => void {
  const t = useTranslations("data.problem");
  return useCallback(
    (error: unknown) => {
      if (isApiProblem(error)) {
        toast.error(
          error.title,
          error.traceId ? { description: t("reference", { traceId: error.traceId }) } : {},
        );
        return;
      }
      toast.error(t("unknown"), {});
    },
    [t],
  );
}

/** A validation problem's body errors keyed by form field (`#/location/city` is `location.city`). */
export function fieldErrors(problem: ApiProblem): Record<string, string> {
  const result: Record<string, string> = {};
  for (const error of problem.errors) {
    if (!error.pointer?.startsWith("#/")) continue;
    const field = error.pointer
      .slice(2)
      .split("/")
      .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
      .join(".");
    result[field] ??= error.detail;
  }
  return result;
}
