"use client";

import { Button, Input, Label, Select, type SelectOption } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { useUrlTableState } from "@/data/use-url-table-state";
import { DASHBOARD_FILTERS, type DataFilter, INTERVIEW_STATUSES, PIPELINE_STATUSES } from "./model";

const DATA_FILTERS: readonly DataFilter[] = ["recruiter", "team", "job", "department"];

interface DashboardFiltersProps {
  /** Choices for the organisation-data filters; a filter without choices is disabled. */
  options?: Partial<Record<DataFilter, SelectOption[]>>;
}

/** The PRD §10 filters, kept in the URL so a filtered dashboard can be shared or reloaded. */
export function DashboardFilters({ options = {} }: DashboardFiltersProps) {
  const t = useTranslations("dashboard.filters");
  const statuses = useTranslations("dashboard.pipeline.status");
  const interviewStatuses = useTranslations("dashboard.interviewStatus");
  const base = useId();
  const { filters, setFilters } = useUrlTableState(DASHBOARD_FILTERS);
  const set = (name: string, value: string) => setFilters({ ...filters, [name]: value });
  const id = (name: string) => `${base}-${name}`;

  return (
    <section
      aria-labelledby={id("title")}
      className="rounded-lg border border-border bg-surface p-4"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id={id("title")} className="font-semibold text-sm">
          {t("title")}
        </h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setFilters({})}
          disabled={Object.keys(filters).length === 0}
        >
          {t("clear")}
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(["from", "to"] as const).map((name) => (
          <div key={name} className="flex flex-col gap-1">
            <Label htmlFor={id(name)}>{t(name)}</Label>
            <Input
              id={id(name)}
              type="date"
              value={filters[name] ?? ""}
              onChange={(event) => set(name, event.target.value)}
            />
          </div>
        ))}
        {DATA_FILTERS.map((name) => {
          const choices = options[name] ?? [];
          return (
            <div key={name} className="flex flex-col gap-1">
              <Label htmlFor={id(name)}>{t(name)}</Label>
              <Select
                id={id(name)}
                options={choices}
                placeholder={t("any")}
                value={filters[name] ?? ""}
                onValueChange={(value) => set(name, value)}
                disabled={choices.length === 0}
              />
            </div>
          );
        })}
        <div className="flex flex-col gap-1">
          <Label htmlFor={id("candidateStatus")}>{t("candidateStatus")}</Label>
          <Select
            id={id("candidateStatus")}
            options={PIPELINE_STATUSES.map((status) => ({
              value: status,
              label: statuses(status),
            }))}
            placeholder={t("any")}
            value={filters.candidateStatus ?? ""}
            onValueChange={(value) => set("candidateStatus", value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor={id("interviewStatus")}>{t("interviewStatus")}</Label>
          <Select
            id={id("interviewStatus")}
            options={INTERVIEW_STATUSES.map((status) => ({
              value: status,
              label: interviewStatuses(status),
            }))}
            placeholder={t("any")}
            value={filters.interviewStatus ?? ""}
            onValueChange={(value) => set("interviewStatus", value)}
          />
        </div>
      </div>
    </section>
  );
}
