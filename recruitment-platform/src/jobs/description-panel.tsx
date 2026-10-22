"use client";

import {
  Button,
  Checkbox,
  Input,
  Label,
  NativeSelect,
  RadioGroup,
  RadioItem,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { useIdempotencyKey } from "@/data/idempotency";
import { QueryFailed } from "@/data/query-failed";
import {
  applyDescription,
  getDescription,
  type Job,
  type JobDescription,
  type JobFields,
  retryDocument,
  submitDescription,
} from "./api";
import { keys } from "./queries";
import type { SkillValue } from "./skill-picker";

const POLL_MS = 2_000;
const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.txt,application/pdf,text/plain";
const FINAL = new Set(["parsed", "quarantined", "failed"]);
const ERRORS = [
  "unreadable",
  "too-many-pages",
  "no-text",
  "ai-failed",
  "budget-exceeded",
  "retries-exhausted",
] as const;
const WORK_MODELS = ["onsite", "hybrid", "remote"] as const;
type WorkModel = Exclude<JobFields["work_model"], undefined>;

/** What the pipeline found (see `hirevion_core.documents.pipeline`). */
interface Extraction {
  title: string | null;
  required_skills: { name: string; quote: string }[];
  preferred_skills: { name: string; quote: string }[];
  experience_min: number | null;
  experience_max: number | null;
  responsibilities: { text: string }[];
  qualifications: { text: string }[];
  domain: { text: string }[];
  location: string | null;
  work_model: (typeof WORK_MODELS)[number] | null;
  dropped: number;
  /** The description was longer than the AI is given, so its end wasn't read. */
  truncated?: boolean;
}

/** The job's description (PRD §12): send one, follow it being read, then review and apply. */
export function DescriptionPanel({
  job,
  canEdit,
  pollMs = POLL_MS,
  active = true,
}: {
  job: Job;
  canEdit: boolean;
  pollMs?: number;
  /** False while the panel is kept mounted behind another tab: it doesn't poll then. */
  active?: boolean;
}) {
  const t = useTranslations("jobs.description");
  const [replacing, setReplacing] = useState(false);
  const description = useQuery({
    queryKey: keys.description(job.id),
    queryFn: () => getDescription(job.id),
    refetchInterval: (query) => {
      const data = query.state.data;
      return active && data && !FINAL.has(data.status) ? pollMs : false;
    },
  });

  if (description.isPending) return <Skeleton className="h-40 w-full" />;
  // A failed load is not "no description": the upload form would invite replacing one.
  if (description.isError) return <QueryFailed onRetry={() => void description.refetch()} />;
  const current = description.data ?? null;
  const intro = <p className="text-muted-foreground text-sm">{t("intro")}</p>;
  if (current === null || replacing) {
    return canEdit ? (
      <div className="grid max-w-3xl gap-4">
        {intro}
        <SubmitForm
          jobId={job.id}
          onSent={() => setReplacing(false)}
          onCancel={current === null ? undefined : () => setReplacing(false)}
        />
      </div>
    ) : (
      <p className="text-muted-foreground text-sm">{t("none")}</p>
    );
  }

  const replace = canEdit ? (
    <Button variant="secondary" className="w-fit" onClick={() => setReplacing(true)}>
      {t("replace")}
    </Button>
  ) : null;
  return (
    <div className="grid max-w-3xl gap-4">
      <p className="text-muted-foreground text-sm">
        {t("source", { name: current.filename ?? t("pasted") })}
      </p>
      {current.status === "parsed" && current.extraction ? (
        canEdit ? (
          <ReviewForm job={job} document={current} />
        ) : null
      ) : (
        <Progress document={current} canEdit={canEdit} />
      )}
      {replace}
    </div>
  );
}

function Progress({ document, canEdit }: { document: JobDescription; canEdit: boolean }) {
  const t = useTranslations("jobs.description");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => retryDocument(document.id),
    onSuccess: () => {
      toast.success(t("retried"), {});
      void queryClient.invalidateQueries({ queryKey: ["jobs", "detail"] });
    },
    onError: problems.show,
  });

  if (document.status === "quarantined") {
    return (
      <p role="alert" className="rounded-md bg-danger-subtle p-3 text-danger text-sm">
        {t("quarantined")}
      </p>
    );
  }
  if (document.status === "failed") {
    const code = (ERRORS as readonly string[]).includes(document.error_code ?? "")
      ? (document.error_code as (typeof ERRORS)[number])
      : "unknown";
    return (
      <div className="grid gap-3 rounded-md bg-warning-subtle p-3">
        <p role="alert" className="text-sm text-warning">
          {t("failed", { reason: t(`errors.${code}`) })}
        </p>
        {canEdit ? (
          <Button className="w-fit" disabled={retry.isPending} onClick={() => retry.mutate()}>
            {t("retry")}
          </Button>
        ) : null}
      </div>
    );
  }
  return (
    <div role="status" className="grid gap-1 rounded-md border border-border p-3">
      <span className="font-medium text-sm">{t(`statuses.${document.status}`)}</span>
      <span className="text-muted-foreground text-xs">{t("working")}</span>
    </div>
  );
}

function SubmitForm({
  jobId,
  onSent,
  onCancel,
}: {
  jobId: string;
  onSent: () => void;
  /** Present when there is a description to go back to. */
  onCancel?: (() => void) | undefined;
}) {
  const t = useTranslations("jobs.description");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const key = useIdempotencyKey();
  const [mode, setMode] = useState<"paste" | "upload">("paste");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  function problem(): string | null {
    if (mode === "paste") return text.trim() ? null : t("textRequired");
    if (!file) return t("fileRequired");
    if (file.size > MAX_BYTES) return t("tooLarge");
    if (!/\.(pdf|docx|txt)$/i.test(file.name)) return t("wrongType");
    return null;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = problem();
    setError(found);
    if (found) return;
    setSending(true);
    try {
      await submitDescription(
        jobId,
        mode === "paste" || !file ? { text: text.trim() } : { file },
        key.current(),
      );
      key.renew();
      toast.success(t("submitted"), {});
      await queryClient.invalidateQueries({ queryKey: keys.description(jobId) });
      onSent();
    } catch (failure) {
      problems.show(failure);
    } finally {
      setSending(false);
    }
  }

  const errorId = `${id}-error`;
  return (
    <form noValidate onSubmit={submit} className="grid gap-4">
      <RadioGroup
        value={mode}
        onValueChange={(next) => {
          setMode(next as "paste" | "upload");
          setError(null);
        }}
        className="flex flex-wrap gap-4"
      >
        {(["paste", "upload"] as const).map((option) => (
          <div key={option} className="flex items-center gap-2">
            <RadioItem id={`${id}-${option}`} value={option} />
            <Label htmlFor={`${id}-${option}`} className="font-normal">
              {t(option)}
            </Label>
          </div>
        ))}
      </RadioGroup>
      {mode === "paste" ? (
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-text`}>{t("text")}</Label>
          <Textarea
            id={`${id}-text`}
            rows={12}
            value={text}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => setText(event.target.value)}
          />
        </div>
      ) : (
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-file`}>{t("file")}</Label>
          <Input
            id={`${id}-file`}
            type="file"
            accept={ACCEPT}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </div>
      )}
      {error ? (
        <p id={errorId} role="alert" className="text-danger text-sm">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" className="w-fit" disabled={sending}>
          {t("submit")}
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t("keepCurrent")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function ReviewForm({ job, document }: { job: Job; document: JobDescription }) {
  const t = useTranslations("jobs.description.review");
  const form = useTranslations("jobs.form");
  const labels = useTranslations("jobs");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const found = document.extraction as unknown as Extraction;
  const extracted = [
    ...found.required_skills.map((skill) => ({ ...skill, importance: "required" as const })),
    ...found.preferred_skills.map((skill) => ({ ...skill, importance: "preferred" as const })),
  ];
  const lines = (items: { text: string }[], fallback: string[]) =>
    (items.length > 0 ? items.map((item) => item.text) : fallback).join("\n");

  const [title, setTitle] = useState(found.title ?? job.title);
  const [kept, setKept] = useState(() => new Set(extracted.map((skill) => skill.name)));
  // What the reviewer decided each skill is: as found, unless they change it.
  const [importance, setImportance] = useState<Record<string, "required" | "preferred">>(() =>
    Object.fromEntries(extracted.map((skill) => [skill.name, skill.importance])),
  );
  const [experienceMin, setExperienceMin] = useState(
    String(found.experience_min ?? job.experience_min ?? ""),
  );
  const [experienceMax, setExperienceMax] = useState(
    String(found.experience_max ?? job.experience_max ?? ""),
  );
  const [workModel, setWorkModel] = useState<string>(found.work_model ?? job.work_model ?? "");
  const [location, setLocation] = useState(found.location ?? job.location ?? "");
  const [responsibilities, setResponsibilities] = useState(
    lines(found.responsibilities, job.responsibilities),
  );
  const [qualifications, setQualifications] = useState(
    lines(found.qualifications, job.qualifications),
  );
  const [domain, setDomain] = useState(lines(found.domain, job.domain));

  const apply = useMutation({
    mutationFn: () => {
      const own: SkillValue[] = job.skills.map((skill) => ({
        name: skill.name,
        importance: skill.importance,
        min_years: skill.min_years,
      }));
      const taken = new Set(own.map((skill) => skill.name.toLowerCase()));
      const added: SkillValue[] = extracted
        .filter((skill) => kept.has(skill.name) && !taken.has(skill.name.toLowerCase()))
        .map((skill) => ({
          name: skill.name,
          importance: importance[skill.name] ?? skill.importance,
          min_years: null,
        }));
      const split = (text: string) =>
        text
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
      const amount = (text: string) => (text.trim() === "" ? null : Number(text));
      return applyDescription(job.id, {
        document_id: document.id,
        title: title.trim() || job.title,
        skills: [...own, ...added],
        experience_min: amount(experienceMin),
        experience_max: amount(experienceMax),
        work_model: (workModel || null) as WorkModel,
        location: location.trim() || null,
        responsibilities: split(responsibilities),
        qualifications: split(qualifications),
        domain: split(domain),
      });
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.job(job.id), saved);
      void queryClient.invalidateQueries({ queryKey: keys.list });
      toast.success(t("applied"), {});
    },
    onError: problems.show,
  });

  const field = (label: string, control: (id: string) => React.ReactNode, name: string) => (
    <div className="grid gap-1.5">
      <Label htmlFor={`${id}-${name}`}>{label}</Label>
      {control(`${id}-${name}`)}
    </div>
  );
  const textarea = (name: string, label: string, value: string, set: (v: string) => void) =>
    field(
      label,
      (control) => (
        <Textarea
          id={control}
          rows={4}
          value={value}
          aria-describedby={`${id}-lines`}
          onChange={(event) => set(event.target.value)}
        />
      ),
      name,
    );

  return (
    <form
      noValidate
      className="grid gap-4 rounded-lg border border-border p-4"
      onSubmit={(event) => {
        event.preventDefault();
        apply.mutate();
      }}
    >
      <div className="grid gap-1">
        <h3 className="font-semibold text-base">{t("title")}</h3>
        <p className="text-muted-foreground text-sm">{t("hint")}</p>
        {found.dropped > 0 ? (
          <p className="text-sm text-warning">{t("dropped", { count: found.dropped })}</p>
        ) : null}
        {found.truncated ? <p className="text-sm text-warning">{t("truncated")}</p> : null}
      </div>
      {field(
        form("title"),
        (control) => (
          <Input id={control} value={title} onChange={(event) => setTitle(event.target.value)} />
        ),
        "title",
      )}
      {(["required", "preferred"] as const).map((group) => {
        const skills = extracted.filter((skill) => skill.importance === group);
        if (skills.length === 0) return null;
        return (
          <fieldset key={group} className="grid gap-2">
            <legend className="mb-1 font-medium text-sm">
              {t(group === "required" ? "requiredSkills" : "preferredSkills")}
            </legend>
            <ul className="grid gap-2">
              {skills.map((skill, position) => {
                // (A skill's name may have spaces; an id may not.)
                const control = `${id}-skill-${group}-${position}`;
                return (
                  <li key={skill.name} className="flex items-start gap-2">
                    <Checkbox
                      id={control}
                      className="mt-0.5"
                      checked={kept.has(skill.name)}
                      aria-describedby={`${control}-quote`}
                      onCheckedChange={(checked) =>
                        setKept((previous) => {
                          const next = new Set(previous);
                          if (checked === true) next.add(skill.name);
                          else next.delete(skill.name);
                          return next;
                        })
                      }
                    />
                    <div className="grid gap-0.5">
                      <Label htmlFor={control} className="font-normal">
                        {skill.name}
                      </Label>
                      <span id={`${control}-quote`} className="text-muted-foreground text-xs">
                        {t("quote", { quote: skill.quote })}
                      </span>
                    </div>
                    <NativeSelect
                      aria-label={t("treatAs", { name: skill.name })}
                      className="ml-auto w-32"
                      value={importance[skill.name] ?? skill.importance}
                      onChange={(event) =>
                        setImportance((previous) => ({
                          ...previous,
                          [skill.name]: event.target.value as "required" | "preferred",
                        }))
                      }
                      options={[
                        { value: "required", label: t("required") },
                        { value: "preferred", label: t("preferred") },
                      ]}
                    />
                  </li>
                );
              })}
            </ul>
          </fieldset>
        );
      })}
      <div className="grid gap-4 sm:grid-cols-2">
        {field(
          form("experienceMin"),
          (control) => (
            <Input
              id={control}
              type="number"
              min={0}
              max={60}
              value={experienceMin}
              onChange={(event) => setExperienceMin(event.target.value)}
            />
          ),
          "experience-min",
        )}
        {field(
          form("experienceMax"),
          (control) => (
            <Input
              id={control}
              type="number"
              min={0}
              max={60}
              value={experienceMax}
              onChange={(event) => setExperienceMax(event.target.value)}
            />
          ),
          "experience-max",
        )}
        {field(
          form("workModel"),
          (control) => (
            <NativeSelect
              id={control}
              value={workModel}
              onChange={(event) => setWorkModel(event.target.value)}
              options={[
                { value: "", label: form("none") },
                ...WORK_MODELS.map((model) => ({
                  value: model,
                  label: labels(`workModels.${model}`),
                })),
              ]}
            />
          ),
          "work-model",
        )}
        {field(
          form("location"),
          (control) => (
            <Input
              id={control}
              value={location}
              onChange={(event) => setLocation(event.target.value)}
            />
          ),
          "location",
        )}
      </div>
      {textarea(
        "responsibilities",
        form("responsibilities"),
        responsibilities,
        setResponsibilities,
      )}
      {textarea("qualifications", form("qualifications"), qualifications, setQualifications)}
      {textarea("domain", form("domain"), domain, setDomain)}
      <p id={`${id}-lines`} className="text-muted-foreground text-xs">
        {form("oneByLine")}
      </p>
      <Button type="submit" className="w-fit" disabled={apply.isPending}>
        {t("apply")}
      </Button>
    </form>
  );
}
