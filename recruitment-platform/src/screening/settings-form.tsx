"use client";

import { Button, Checkbox, Input, Label, Skeleton, Switch, toast } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { QueryFailed } from "@/data/query-failed";
import {
  getJobScreeningConfig,
  getScreeningDefaults,
  resetJobScreeningConfig,
  type ScreeningConfig,
  type ScreeningConfigUpdate,
  saveJobScreeningConfig,
  saveScreeningDefaults,
} from "./api";

export const FACTORS = [
  "required_skills",
  "experience",
  "projects",
  "preferred_skills",
  "domain",
  "education",
  "location",
] as const;
export type Factor = (typeof FACTORS)[number];

export const keys = {
  job: (jobId: string) => ["jobs", "detail", jobId, "screening-config"] as const,
  defaults: ["screening", "defaults"] as const,
};

/** PRD §17's weights, knock-out flags and blind mode. */
export function SettingsForm({
  value,
  onSave,
  saving,
  readOnly = false,
  canChangeBlind = false,
}: {
  value: ScreeningConfig;
  onSave: (body: ScreeningConfigUpdate) => void;
  saving: boolean;
  readOnly?: boolean;
  /** Whether the reader may turn blind screening off (an organisation administrator). */
  canChangeBlind?: boolean;
}) {
  const t = useTranslations("screening");
  const id = useId();
  const [weights, setWeights] = useState<Record<string, string>>(() =>
    Object.fromEntries(FACTORS.map((factor) => [factor, String(value.weights[factor] ?? 0)])),
  );
  const [knockouts, setKnockouts] = useState({
    required_skills: value.knockouts.required_skills ?? true,
    min_experience: value.knockouts.min_experience ?? true,
  });
  const [blind, setBlind] = useState(value.blind);
  const numbers = Object.fromEntries(
    FACTORS.map((factor) => [factor, Number.parseInt(weights[factor] || "0", 10) || 0]),
  );
  const total = Object.values(numbers).reduce((sum, weight) => sum + weight, 0);
  const valid = total === 100 && Object.values(numbers).every((n) => n >= 0 && n <= 100);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    onSave({ weights: numbers, knockouts, blind });
  }

  return (
    <form noValidate onSubmit={submit} className="grid max-w-2xl gap-5">
      <fieldset className="grid gap-3" disabled={readOnly}>
        <legend className="mb-1 font-medium text-sm">{t("settings.weights")}</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          {FACTORS.map((factor) => (
            <div key={factor} className="grid gap-1">
              <Label htmlFor={`${id}-${factor}`}>{t(`factors.${factor}`)}</Label>
              <Input
                id={`${id}-${factor}`}
                type="number"
                min={0}
                max={100}
                step={1}
                inputMode="numeric"
                value={weights[factor] ?? ""}
                onChange={(event) =>
                  setWeights((previous) => ({ ...previous, [factor]: event.target.value }))
                }
              />
            </div>
          ))}
        </div>
        <p
          role={valid ? undefined : "alert"}
          className={valid ? "text-muted-foreground text-sm" : "text-danger text-sm"}
        >
          {valid ? t("settings.total", { total }) : t("settings.totalWrong", { total })}
        </p>
      </fieldset>
      <fieldset className="grid gap-2" disabled={readOnly}>
        <legend className="mb-1 font-medium text-sm">{t("settings.knockouts")}</legend>
        {(
          [
            ["required_skills", "knockoutRequired"],
            ["min_experience", "knockoutExperience"],
          ] as const
        ).map(([key, label]) => (
          <div key={key} className="flex items-center gap-2">
            <Checkbox
              id={`${id}-k-${key}`}
              checked={knockouts[key]}
              onCheckedChange={(checked) =>
                setKnockouts((previous) => ({ ...previous, [key]: checked === true }))
              }
            />
            <Label htmlFor={`${id}-k-${key}`} className="font-normal">
              {t(`settings.${label}`)}
            </Label>
          </div>
        ))}
      </fieldset>
      <div className="grid gap-1">
        <div className="flex items-center gap-2">
          <Switch
            id={`${id}-blind`}
            checked={blind}
            disabled={readOnly || (blind && !canChangeBlind)}
            onCheckedChange={setBlind}
            aria-describedby={`${id}-blind-hint`}
          />
          <Label htmlFor={`${id}-blind`}>{t("settings.blind")}</Label>
        </div>
        <p id={`${id}-blind-hint`} className="text-muted-foreground text-xs">
          {t("settings.blindHint")}
        </p>
        {!blind ? (
          <p role="status" className="text-warning text-xs">
            {t("settings.blindOffWarning")}
          </p>
        ) : null}
        {blind && !canChangeBlind && !readOnly ? (
          <p className="text-muted-foreground text-xs">{t("settings.blindLocked")}</p>
        ) : null}
      </div>
      {readOnly ? null : (
        <Button type="submit" className="w-fit" disabled={!valid || saving}>
          {t("settings.save")}
        </Button>
      )}
    </form>
  );
}

/** A job's Screening tab: its own settings, or the default it inherits. */
export function JobScreeningSettings({
  jobId,
  canEdit,
  canChangeBlind = false,
}: {
  jobId: string;
  canEdit: boolean;
  canChangeBlind?: boolean;
}) {
  const t = useTranslations("screening.settings");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: keys.job(jobId),
    queryFn: () => getJobScreeningConfig(jobId),
  });
  const save = useMutation({
    mutationFn: (body: ScreeningConfigUpdate) => saveJobScreeningConfig(jobId, body),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.job(jobId), saved);
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });
  const reset = useMutation({
    mutationFn: () => resetJobScreeningConfig(jobId),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.job(jobId), saved);
      toast.success(t("resetDone"), {});
    },
    onError: problems.show,
  });

  if (settings.isPending) return <Skeleton className="h-64 w-full" />;
  if (settings.isError) return <QueryFailed onRetry={() => void settings.refetch()} />;
  if (!settings.data) return null;
  const current = settings.data;
  return (
    <div className="grid gap-4">
      <div className="grid gap-1">
        <p className="text-muted-foreground text-sm">{t("jobIntro")}</p>
        <p className="text-sm">
          {current.inherited ? t("inherited") : t("own")}{" "}
          <span className="text-muted-foreground">
            {t("version", { version: current.version })}
          </span>
        </p>
        {canEdit ? null : <p className="text-muted-foreground text-sm">{t("readOnly")}</p>}
      </div>
      <SettingsForm
        key={`${current.source}-${current.version}`}
        value={current}
        onSave={(body) => save.mutate(body)}
        saving={save.isPending}
        readOnly={!canEdit}
        canChangeBlind={canChangeBlind}
      />
      {canEdit && !current.inherited ? (
        <Button
          variant="ghost"
          className="w-fit"
          disabled={reset.isPending}
          onClick={() => reset.mutate()}
        >
          {t("reset")}
        </Button>
      ) : null}
    </div>
  );
}

/** The organisation's defaults, on the organisation profile page. */
export function ScreeningDefaults() {
  const t = useTranslations("screening.settings");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: keys.defaults, queryFn: getScreeningDefaults });
  const save = useMutation({
    mutationFn: saveScreeningDefaults,
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.defaults, saved);
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });
  return (
    <section className="grid gap-3 rounded-lg border border-border p-4">
      <h2 className="font-semibold text-base">{t("defaultsTitle")}</h2>
      <p className="text-muted-foreground text-sm">{t("defaultsIntro")}</p>
      {settings.data ? (
        <SettingsForm
          key={settings.data.version}
          value={settings.data}
          onSave={(body) => save.mutate(body)}
          saving={save.isPending}
          canChangeBlind
        />
      ) : settings.isError ? (
        <QueryFailed onRetry={() => void settings.refetch()} />
      ) : (
        <Skeleton className="h-48 w-full" />
      )}
    </section>
  );
}
