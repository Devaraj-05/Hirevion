"use client";

import { isApiProblem } from "@hirevion/api-client";
import { toast } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useCallback } from "react";
import type { FieldValues, Path, UseFormReturn } from "react-hook-form";
import { fieldErrors, useProblemToast } from "@/data/problems";

/** The administration API's refusals, in the reader's language where we know the code. */
export function useAdminProblem() {
  const t = useTranslations("admin.problems");
  const showProblem = useProblemToast();

  const message = useCallback(
    (error: unknown): string | null =>
      isApiProblem(error) && t.has(error.code as "name-taken")
        ? t(error.code as "name-taken")
        : null,
    [t],
  );

  /** Shows a refusal as a toast; a cancelled password confirmation needs no message. */
  const show = useCallback(
    (error: unknown) => {
      if (isApiProblem(error) && error.code === "step-up-required") return;
      const known = message(error);
      if (known) toast.error(known, {});
      else showProblem(error);
    },
    [message, showProblem],
  );

  /**
   * Puts a refusal on the form fields it names (`fields` maps the API's field names to the
   * form's) and returns true; anything without a field is left to the caller.
   */
  const onForm = useCallback(
    <T extends FieldValues>(
      form: UseFormReturn<T>,
      error: unknown,
      fields: Record<string, Path<T>>,
    ): boolean => {
      if (!isApiProblem(error)) return false;
      let placed = false;
      for (const [field, detail] of Object.entries(fieldErrors(error))) {
        const target = fields[field];
        if (target) {
          form.setError(target, { message: message(error) ?? detail });
          placed = true;
        }
      }
      return placed;
    },
    [message],
  );

  return { message, show, onForm };
}
