"use client";

import { Checkbox, Label, RadioGroup, RadioItem } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useId } from "react";

export interface ChoiceOption {
  value: string;
  label: string;
  disabled?: boolean;
  /** Shown under the label and read with the checkbox. */
  hint?: string;
}

interface CheckboxGroupProps {
  legend: string;
  options: readonly ChoiceOption[];
  value: readonly string[];
  onChange: (value: string[]) => void;
  error?: string | undefined;
  /** Shown instead of the list when there's nothing to choose. */
  emptyText?: string;
}

/** Several choices under one legend (roles, teams, permissions). */
export function CheckboxGroup({
  legend,
  options,
  value,
  onChange,
  error,
  emptyText,
}: CheckboxGroupProps) {
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <fieldset className="grid gap-2" aria-describedby={error ? errorId : undefined}>
      <legend className="mb-1 font-medium text-sm">{legend}</legend>
      {options.length === 0 && emptyText ? (
        <p className="text-muted-foreground text-sm">{emptyText}</p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {options.map((option) => {
            const optionId = `${id}-${option.value}`;
            const hintId = `${optionId}-hint`;
            return (
              <li key={option.value} className="flex items-start gap-2">
                <Checkbox
                  id={optionId}
                  className="mt-0.5"
                  checked={value.includes(option.value)}
                  disabled={option.disabled}
                  aria-describedby={option.hint ? hintId : undefined}
                  onCheckedChange={(checked) =>
                    onChange(
                      checked === true
                        ? [...value, option.value]
                        : value.filter((item) => item !== option.value),
                    )
                  }
                />
                <div className="grid gap-0.5">
                  <Label htmlFor={optionId} className="font-normal">
                    {option.label}
                  </Label>
                  {option.hint ? (
                    <span id={hintId} className="text-muted-foreground text-xs">
                      {option.hint}
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {error ? (
        <p id={errorId} role="alert" className="text-danger text-sm">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}

/** Whether someone reaches the whole organisation's work or only their teams' (ADR-0014). */
export function AccessChoice({
  value,
  onChange,
}: {
  value: "organization" | "teams";
  onChange: (value: "organization" | "teams") => void;
}) {
  const t = useTranslations("admin.users");
  const id = useId();
  return (
    <fieldset className="grid gap-2" aria-describedby={`${id}-hint`}>
      <legend className="mb-1 font-medium text-sm">{t("access")}</legend>
      <RadioGroup
        value={value}
        onValueChange={(next) => onChange(next as "organization" | "teams")}
        className="flex flex-wrap gap-4"
      >
        {(["organization", "teams"] as const).map((scope) => (
          <div key={scope} className="flex items-center gap-2">
            <RadioItem id={`${id}-${scope}`} value={scope} />
            <Label htmlFor={`${id}-${scope}`} className="font-normal">
              {t(`scopes.${scope}`)}
            </Label>
          </div>
        ))}
      </RadioGroup>
      <p id={`${id}-hint`} className="text-muted-foreground text-xs">
        {t("scopeHint")}
      </p>
    </fieldset>
  );
}
