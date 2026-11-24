"use client";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  Input,
  Label,
  NativeSelect,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { listTemplates } from "./api";
import {
  assignInterviews,
  type BulkResult,
  CODING_LANGUAGES,
  type CodingChoice,
  type CodingLanguage,
  interviewKeys,
  isoToLocal,
  localToIso,
} from "./assigned-api";

type CodingMode = "template" | "on" | "off";
const LEVELS = ["easy", "medium", "hard"] as const;

const DAY_MS = 86_400_000;

/** "Create interview" (PRD §24): the chosen candidates, a template (or each job's own), a
 * window, and whether to invite them now. Reports the candidates it skipped and why. */
export function AssignDialog({
  applicationIds,
  names = {},
  defaultTemplateId,
  onDone,
  onCancel,
}: {
  applicationIds: string[];
  /** Candidates' names by application, to say who was skipped. */
  names?: Record<string, string>;
  defaultTemplateId?: string | null;
  onDone: (result: BulkResult) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("interviews.assign");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const tomorrow = new Date(Date.now() + DAY_MS);
  tomorrow.setMinutes(0, 0, 0);
  const [templateId, setTemplateId] = useState(defaultTemplateId ?? "");
  const [startsAt, setStartsAt] = useState(isoToLocal(tomorrow));
  const [expiresAt, setExpiresAt] = useState(isoToLocal(new Date(tomorrow.getTime() + 2 * DAY_MS)));
  const [invite, setInvite] = useState(true);
  // The coding question (C8-11, owner 2026-11-22: "decide by the recruiter at interview
  // scheduling time"): the template's unless the recruiter chooses.
  const [codingMode, setCodingMode] = useState<CodingMode>("template");
  const [languages, setLanguages] = useState<CodingLanguage[]>(["python"]);
  const [minutes, setMinutes] = useState("20");
  const [level, setLevel] = useState<CodingChoice["difficulty"]>("medium");
  const [skipped, setSkipped] = useState<BulkResult["skipped"]>([]);
  const templates = useQuery({
    queryKey: ["interview-templates", "choices"],
    queryFn: () => listTemplates({ status: "active", limit: 100 }),
  });

  const assign = useMutation({
    mutationFn: () =>
      assignInterviews({
        application_ids: applicationIds,
        template_id: templateId || null,
        starts_at: localToIso(startsAt),
        expires_at: localToIso(expiresAt),
        invite,
        coding: codingChoice(),
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: interviewKeys.list });
      if (result.created.length > 0) {
        toast.success(t("created", { count: result.created.length }), {});
      }
      if (result.skipped.length > 0) setSkipped(result.skipped);
      else onDone(result);
    },
    onError: problems.show,
  });

  const minutesValue = Number(minutes);
  // The API takes 5 to 45 whole minutes; a leftover typo never matters once coding is off.
  const minutesInvalid =
    codingMode === "on" &&
    !(Number.isInteger(minutesValue) && minutesValue >= 5 && minutesValue <= 45);

  function codingChoice(): CodingChoice | null {
    if (codingMode === "template") return null;
    if (codingMode === "off") {
      return { enabled: false, languages: ["python"], minutes: 20, difficulty: level };
    }
    return {
      enabled: true,
      languages: languages.length > 0 ? languages : ["python"],
      minutes: minutesValue,
      difficulty: level,
    };
  }

  const chosen = templates.data?.items.find((template) => template.id === templateId);

  function submit(event: FormEvent) {
    event.preventDefault();
    assign.mutate();
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (open) return;
        // Once interviews were created, closing any way reports them, so the list refreshes.
        if (assign.data) onDone({ created: assign.data.created, skipped });
        else onCancel();
      }}
    >
      <DialogContent
        title={t("title", { count: applicationIds.length })}
        description={t("description")}
        closeLabel={t("cancel")}
      >
        {skipped.length > 0 ? (
          <div className="grid gap-3">
            <p className="text-sm" role="status">
              {t("skippedTitle", { count: skipped.length })}
            </p>
            <ul className="grid gap-1 text-sm">
              {skipped.map((item) => (
                <li key={item.application_id}>
                  {t("skippedLine", {
                    name: names[item.application_id] ?? t("someone"),
                    reason: t(`skipped.${skippedCode(item.code)}`),
                  })}
                </li>
              ))}
            </ul>
            <div className="flex justify-end">
              <Button
                onClick={() => onDone({ created: assign.data?.created ?? [], skipped })}
                type="button"
              >
                {t("close")}
              </Button>
            </div>
          </div>
        ) : (
          <form noValidate onSubmit={submit} className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-template`}>{t("template")}</Label>
              <NativeSelect
                id={`${id}-template`}
                value={templateId}
                onChange={(event) => setTemplateId(event.target.value)}
                options={[
                  { value: "", label: t("jobTemplate") },
                  ...(templates.data?.items ?? []).map((template) => ({
                    value: template.id,
                    label: t("templateOption", {
                      name: template.name,
                      minutes: template.duration_minutes,
                    }),
                  })),
                ]}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-starts`}>{t("startsAt")}</Label>
                <Input
                  id={`${id}-starts`}
                  type="datetime-local"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-expires`}>{t("expiresAt")}</Label>
                <Input
                  id={`${id}-expires`}
                  type="datetime-local"
                  value={expiresAt}
                  onChange={(event) => setExpiresAt(event.target.value)}
                />
              </div>
            </div>
            <fieldset className="grid gap-3 rounded-md border p-3">
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-coding`}>{t("coding.label")}</Label>
                <NativeSelect
                  id={`${id}-coding`}
                  value={codingMode}
                  onChange={(event) => setCodingMode(event.target.value as CodingMode)}
                  options={[
                    {
                      value: "template",
                      label: chosen
                        ? chosen.coding
                          ? t("coding.templateOn", {
                              languages: chosen.coding_languages
                                .map((lang) => t(`coding.languages.${lang as CodingLanguage}`))
                                .join(", "),
                              minutes: chosen.coding_minutes,
                            })
                          : t("coding.templateOff")
                        : t("coding.asTemplate"),
                    },
                    { value: "on", label: t("coding.on") },
                    { value: "off", label: t("coding.off") },
                  ]}
                />
              </div>
              {codingMode === "on" ? (
                <>
                  <fieldset className="flex flex-wrap gap-x-4 gap-y-2">
                    <legend className="sr-only">{t("coding.languagesLabel")}</legend>
                    {CODING_LANGUAGES.map((lang) => (
                      <div key={lang} className="flex items-center gap-2">
                        <Checkbox
                          id={`${id}-lang-${lang}`}
                          checked={languages.includes(lang)}
                          onCheckedChange={(checked) =>
                            setLanguages((now) =>
                              checked === true
                                ? CODING_LANGUAGES.filter(
                                    (one) => one === lang || now.includes(one),
                                  )
                                : now.filter((one) => one !== lang),
                            )
                          }
                        />
                        <Label htmlFor={`${id}-lang-${lang}`}>
                          {t(`coding.languages.${lang}`)}
                        </Label>
                      </div>
                    ))}
                  </fieldset>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="grid gap-1.5">
                      <Label htmlFor={`${id}-minutes`}>{t("coding.minutes")}</Label>
                      <Input
                        id={`${id}-minutes`}
                        type="number"
                        min={5}
                        max={45}
                        step={1}
                        value={minutes}
                        aria-invalid={minutesInvalid || undefined}
                        aria-describedby={minutesInvalid ? `${id}-minutes-error` : undefined}
                        onChange={(event) => setMinutes(event.target.value)}
                      />
                      {minutesInvalid ? (
                        <p id={`${id}-minutes-error`} className="text-destructive text-xs">
                          {t("coding.minutesInvalid")}
                        </p>
                      ) : null}
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor={`${id}-level`}>{t("coding.level")}</Label>
                      <NativeSelect
                        id={`${id}-level`}
                        value={level}
                        onChange={(event) =>
                          setLevel(event.target.value as CodingChoice["difficulty"])
                        }
                        options={LEVELS.map((one) => ({
                          value: one,
                          label: t(`coding.levels.${one}`),
                        }))}
                      />
                    </div>
                  </div>
                  <p className="text-muted-foreground text-xs">{t("coding.hint")}</p>
                </>
              ) : null}
            </fieldset>
            <div className="flex items-center gap-2">
              <Checkbox
                id={`${id}-invite`}
                checked={invite}
                onCheckedChange={(checked) => setInvite(checked === true)}
              />
              <Label htmlFor={`${id}-invite`}>{t("invite")}</Label>
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={onCancel}>
                {t("cancel")}
              </Button>
              <Button
                type="submit"
                disabled={assign.isPending || !startsAt || !expiresAt || minutesInvalid}
              >
                {invite ? t("submitInvite") : t("submitSchedule")}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

const KNOWN = [
  "no-email",
  "already-assigned",
  "stage",
  "job-not-open",
  "no-template",
  "template-unavailable",
  "application-not-found",
  "invalid-window",
  "window-past",
  "window-too-short",
  "window-too-long",
  "coding-too-long",
] as const;

/** The message key for a skip code; anything new reads as "couldn't be assigned". */
function skippedCode(code: string): (typeof KNOWN)[number] | "other" {
  return (KNOWN as readonly string[]).includes(code) ? (code as (typeof KNOWN)[number]) : "other";
}
