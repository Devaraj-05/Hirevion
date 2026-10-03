"use client";

import { Button, Input, NativeSelect } from "@hirevion/ui";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { type KeyboardEvent, useEffect, useId, useState } from "react";
import { suggestSkills } from "./api";
import { keys } from "./queries";

export const IMPORTANCES = ["required", "preferred", "optional"] as const;
export type Importance = (typeof IMPORTANCES)[number];

/** A skill as the job form holds it. */
export interface SkillValue {
  name: string;
  importance: Importance;
  min_years: number | null;
}
const SEARCH_DELAY_MS = 250;

/** The skills a job asks for, each with its importance (PRD §17). Typing suggests skills from
 * the shared taxonomy; Enter adds the text as typed, which the API matches to a skill if it can. */
export function SkillPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: readonly SkillValue[];
  onChange: (skills: SkillValue[]) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("jobs.skills");
  const id = useId();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);
  const suggestions = useQuery({
    queryKey: keys.skills(query),
    queryFn: () => suggestSkills(query),
    enabled: query.length > 0,
    staleTime: 60_000,
  });
  const taken = new Set(value.map((skill) => skill.name.toLowerCase()));
  const offered = (suggestions.data ?? []).filter((skill) => !taken.has(skill.name.toLowerCase()));

  function add(name: string) {
    const cleaned = name.trim();
    if (!cleaned || taken.has(cleaned.toLowerCase())) return;
    onChange([...value, { name: cleaned, importance: "required", min_years: null }]);
    setText("");
    setQuery("");
  }

  function update(index: number, changes: Partial<SkillValue>) {
    onChange(value.map((skill, at) => (at === index ? { ...skill, ...changes } : skill)));
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      add(text);
    }
  }

  return (
    <fieldset className="grid gap-2" disabled={disabled}>
      <legend className="mb-1 font-medium text-sm">{t("label")}</legend>
      {value.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("empty")}</p>
      ) : (
        <ul className="grid gap-2">
          {value.map((skill, index) => (
            <li key={skill.name} className="flex flex-wrap items-center gap-2">
              <span className="min-w-32 flex-1 font-medium text-sm">{skill.name}</span>
              <NativeSelect
                aria-label={t("importance", { name: skill.name })}
                className="w-36"
                value={skill.importance}
                onChange={(event) =>
                  update(index, { importance: event.target.value as Importance })
                }
                options={IMPORTANCES.map((importance) => ({
                  value: importance,
                  label: t(`importances.${importance}`),
                }))}
              />
              <Input
                type="number"
                min={0}
                max={60}
                step={0.5}
                className="w-24"
                aria-label={t("minYears", { name: skill.name })}
                placeholder="—"
                value={skill.min_years ?? ""}
                onChange={(event) =>
                  update(index, {
                    min_years: event.target.value === "" ? null : Number(event.target.value),
                  })
                }
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t("remove", { name: skill.name })}
                onClick={() => onChange(value.filter((_, at) => at !== index))}
              >
                <X className="size-4" aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Input
        id={id}
        aria-label={t("search")}
        aria-describedby={`${id}-hint`}
        placeholder={t("search")}
        autoComplete="off"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <p id={`${id}-hint`} className="text-muted-foreground text-xs">
        {t("searchHint")}
      </p>
      {text.trim() && offered.length > 0 ? (
        <ul aria-label={t("suggestions")} className="flex flex-wrap gap-2">
          {offered.map((skill) => (
            <li key={skill.id}>
              <Button type="button" variant="secondary" size="sm" onClick={() => add(skill.name)}>
                {skill.name}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </fieldset>
  );
}
