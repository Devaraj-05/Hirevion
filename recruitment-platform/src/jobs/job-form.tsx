"use client";

import { Button, Form, FormField, Input, NativeSelect, Textarea, toast } from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type ReactNode, useMemo } from "react";
import { useForm } from "react-hook-form";
import { useAdminProblem } from "@/admin/problems";
import { z } from "@/config/zod";
import { useIdempotencyKey } from "@/data/idempotency";
import { createJob, type Job, type JobFields, updateJob } from "./api";
import { keys, useJobChoices } from "./queries";
import { IMPORTANCES, SkillPicker, type SkillValue } from "./skill-picker";

const NONE = "";
const WORK_MODELS = ["onsite", "hybrid", "remote"] as const;
type WorkModel = Exclude<JobFields["work_model"], undefined>;
const EMPLOYMENT_TYPES = ["full_time", "part_time", "contract", "internship", "temporary"] as const;
// The API's fields, mapped to the form's, for refusals that name a field.
const FIELDS = {
  title: "title",
  department_id: "department_id",
  team_id: "team_id",
  location: "location",
  work_model: "work_model",
  employment_type: "employment_type",
  experience_min: "experience_min",
  experience_max: "experience_max",
  description: "description",
  responsibilities: "responsibilities",
  qualifications: "qualifications",
  domain: "domain",
  salary_min: "salary_min",
  salary_max: "salary_max",
  salary_currency: "salary_currency",
  recruiter_id: "recruiter_id",
  hiring_manager_id: "hiring_manager_id",
  interview_template_id: "interview_template_id",
} as const;

const lines = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
const amount = (text: string) => (text.trim() === "" ? null : Number(text));

function defaults(job: Job | undefined) {
  const text = (value: number | string | null | undefined) =>
    value === null || value === undefined ? "" : String(value);
  return {
    title: job?.title ?? "",
    department_id: job?.department_id ?? NONE,
    team_id: job?.team_id ?? NONE,
    location: job?.location ?? "",
    work_model: job?.work_model ?? NONE,
    employment_type: job?.employment_type ?? "full_time",
    experience_min: text(job?.experience_min),
    experience_max: text(job?.experience_max),
    salary_min: text(job?.salary_min),
    salary_max: text(job?.salary_max),
    salary_currency: job?.salary_currency ?? "",
    recruiter_id: job?.recruiter_id ?? NONE,
    hiring_manager_id: job?.hiring_manager_id ?? NONE,
    interview_template_id: job?.interview_template_id ?? NONE,
    description: job?.description ?? "",
    responsibilities: (job?.responsibilities ?? []).join("\n"),
    qualifications: (job?.qualifications ?? []).join("\n"),
    domain: (job?.domain ?? []).join("\n"),
    skills: (job?.skills ?? []).map(
      (skill): SkillValue => ({
        name: skill.name,
        importance: skill.importance,
        min_years: skill.min_years,
      }),
    ),
  };
}

/** The job's fields (PRD §11). Without `job` it creates one and opens it; with one it edits. */
export function JobForm({ job, readOnly = false }: { job?: Job; readOnly?: boolean }) {
  const t = useTranslations("jobs.form");
  const labels = useTranslations("jobs");
  const problems = useAdminProblem();
  const router = useRouter();
  const queryClient = useQueryClient();
  const choices = useJobChoices();
  const key = useIdempotencyKey();

  const schema = useMemo(() => {
    const years = z
      .string()
      .refine(
        (value) => value.trim() === "" || (Number(value) >= 0 && Number(value) <= 60),
        t("invalidNumber"),
      );
    const money = z
      .string()
      .refine((value) => value.trim() === "" || Number(value) >= 0, t("invalidSalary"));
    const inOrder = (low: string, high: string) =>
      low.trim() === "" || high.trim() === "" || Number(high) >= Number(low);
    return z
      .object({
        title: z.string().trim().min(1, t("titleRequired")),
        department_id: z.string(),
        team_id: z.string(),
        location: z.string(),
        work_model: z.string(),
        employment_type: z.enum(EMPLOYMENT_TYPES),
        experience_min: years,
        experience_max: years,
        salary_min: money,
        salary_max: money,
        salary_currency: z
          .string()
          .refine((value) => /^([A-Za-z]{3})?$/.test(value.trim()), t("currencyFormat")),
        recruiter_id: z.string(),
        hiring_manager_id: z.string(),
        interview_template_id: z.string(),
        description: z.string(),
        responsibilities: z.string(),
        qualifications: z.string(),
        domain: z.string(),
        skills: z.array(
          z.object({
            name: z.string(),
            importance: z.enum(IMPORTANCES),
            min_years: z.number().nullable(),
          }),
        ),
      })
      .refine((values) => inOrder(values.experience_min, values.experience_max), {
        message: t("rangeOrder"),
        path: ["experience_max"],
      })
      .refine((values) => inOrder(values.salary_min, values.salary_max), {
        message: t("rangeOrder"),
        path: ["salary_max"],
      });
  }, [t]);
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: defaults(job) });

  async function submit(values: Values) {
    const body = {
      title: values.title.trim(),
      department_id: values.department_id || null,
      team_id: values.team_id || null,
      location: values.location.trim() || null,
      work_model: (values.work_model || null) as WorkModel,
      employment_type: values.employment_type,
      experience_min: amount(values.experience_min),
      experience_max: amount(values.experience_max),
      salary_min: amount(values.salary_min),
      salary_max: amount(values.salary_max),
      salary_currency: values.salary_currency.trim().toUpperCase() || null,
      recruiter_id: values.recruiter_id || null,
      hiring_manager_id: values.hiring_manager_id || null,
      interview_template_id: values.interview_template_id || null,
      description: values.description,
      responsibilities: lines(values.responsibilities),
      qualifications: lines(values.qualifications),
      domain: lines(values.domain),
      skills: values.skills,
    } satisfies JobFields;
    try {
      if (job) {
        const saved = await updateJob(job.id, body);
        queryClient.setQueryData(keys.job(job.id), saved);
        void queryClient.invalidateQueries({ queryKey: keys.list });
        void queryClient.invalidateQueries({ queryKey: keys.versions(job.id) });
        form.reset(defaults(saved));
        toast.success(t("saved"), {});
      } else {
        const created = await createJob(body, key.current());
        void queryClient.invalidateQueries({ queryKey: keys.list });
        toast.success(t("created", { reference: created.reference }), {});
        router.push(`/jobs/${created.id}`);
      }
    } catch (error) {
      if (!problems.onForm(form, error, FIELDS)) problems.show(error);
    }
  }

  // A person, department or template the job already has stays selectable even when it is no
  // longer offered (someone left, a department was archived): the form must not show "none"
  // for what the job still has, nor drop it on the next save.
  const options = (
    rows: readonly { id: string; name: string }[] | undefined,
    current?: { id: string | null | undefined; name: string | null | undefined },
  ) => [
    { value: NONE, label: t("none") },
    ...(rows ?? []).map((row) => ({ value: row.id, label: row.name })),
    ...(current?.id && !(rows ?? []).some((row) => row.id === current.id)
      ? [{ value: current.id, label: current.name ?? current.id }]
      : []),
  ];
  const select = (
    name:
      | "department_id"
      | "team_id"
      | "recruiter_id"
      | "hiring_manager_id"
      | "interview_template_id"
      | "work_model",
    label: string,
    choices: { value: string; label: string }[],
  ) => (
    <FormField
      control={form.control}
      name={name}
      label={label}
      render={({ ref: _ref, ...field }) => (
        <NativeSelect {...field} disabled={readOnly} options={choices} />
      )}
    />
  );
  const text = (
    name: "title" | "location" | "salary_currency",
    label: string,
    description?: string,
  ) => (
    <FormField
      control={form.control}
      name={name}
      label={label}
      {...(description ? { description } : {})}
      render={(field) => <Input autoComplete="off" disabled={readOnly} {...field} />}
    />
  );
  const number = (
    name: "experience_min" | "experience_max" | "salary_min" | "salary_max",
    label: string,
  ) => (
    <FormField
      control={form.control}
      name={name}
      label={label}
      render={(field) => <Input type="number" min={0} step="any" disabled={readOnly} {...field} />}
    />
  );
  const list = (name: "responsibilities" | "qualifications" | "domain", label: string) => (
    <FormField
      control={form.control}
      name={name}
      label={label}
      description={t("oneByLine")}
      render={(field) => <Textarea rows={4} disabled={readOnly} {...field} />}
    />
  );

  return (
    <Form form={form} onSubmit={submit} className="max-w-3xl">
      {readOnly ? <p className="text-muted-foreground text-sm">{t("readOnly")}</p> : null}
      <Section title={t("basics")}>
        {text("title", t("title"))}
        <div className="grid gap-4 sm:grid-cols-2">
          {text("location", t("location"), t("optional"))}
          {select("work_model", t("workModel"), [
            { value: NONE, label: t("none") },
            ...WORK_MODELS.map((model) => ({
              value: model,
              label: labels(`workModels.${model}`),
            })),
          ])}
          <FormField
            control={form.control}
            name="employment_type"
            label={t("employmentType")}
            render={({ ref: _ref, ...field }) => (
              <NativeSelect
                {...field}
                disabled={readOnly}
                options={EMPLOYMENT_TYPES.map((type) => ({
                  value: type,
                  label: labels(`employmentTypes.${type}`),
                }))}
              />
            )}
          />
        </div>
        <FormField
          control={form.control}
          name="description"
          label={t("description")}
          render={(field) => <Textarea rows={6} disabled={readOnly} {...field} />}
        />
      </Section>
      <Section title={t("assignment")}>
        <div className="grid gap-4 sm:grid-cols-2">
          {select(
            "department_id",
            t("department"),
            options(choices.data?.departments, {
              id: job?.department_id,
              name: job?.department_name,
            }),
          )}
          {select(
            "team_id",
            t("team"),
            options(choices.data?.teams, { id: job?.team_id, name: job?.team_name }),
          )}
          {select(
            "recruiter_id",
            t("recruiter"),
            options(choices.data?.people, { id: job?.recruiter_id, name: job?.recruiter_name }),
          )}
          {select(
            "hiring_manager_id",
            t("hiringManager"),
            options(choices.data?.people, {
              id: job?.hiring_manager_id,
              name: job?.hiring_manager_name,
            }),
          )}
          {select(
            "interview_template_id",
            t("interviewTemplate"),
            options(choices.data?.interview_templates, {
              id: job?.interview_template_id,
              name: job?.interview_template_name,
            }),
          )}
        </div>
      </Section>
      <Section title={t("requirements")}>
        <div className="grid gap-4 sm:grid-cols-2">
          {number("experience_min", t("experienceMin"))}
          {number("experience_max", t("experienceMax"))}
        </div>
        <SkillPicker
          value={form.watch("skills")}
          onChange={(skills) => form.setValue("skills", skills, { shouldDirty: true })}
          disabled={readOnly}
        />
        {list("responsibilities", t("responsibilities"))}
        {list("qualifications", t("qualifications"))}
        {list("domain", t("domain"))}
      </Section>
      <Section title={t("pay")}>
        <div className="grid gap-4 sm:grid-cols-3">
          {number("salary_min", t("salaryMin"))}
          {number("salary_max", t("salaryMax"))}
          {text("salary_currency", t("salaryCurrency"))}
        </div>
      </Section>
      {readOnly ? null : (
        <div className="flex justify-end gap-2">
          {job ? null : (
            <Button type="button" variant="ghost" onClick={() => router.push("/jobs")}>
              {t("cancel")}
            </Button>
          )}
          <Button type="submit" disabled={form.formState.isSubmitting}>
            {job ? t("save") : t("create")}
          </Button>
        </div>
      )}
    </Form>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 rounded-lg border border-border p-4">
      <h2 className="font-semibold text-base">{title}</h2>
      {children}
    </section>
  );
}
