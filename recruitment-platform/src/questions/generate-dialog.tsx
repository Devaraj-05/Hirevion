"use client";

import { Button, Dialog, DialogContent, Input, Label, NativeSelect, toast } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useId, useState } from "react";
import { CheckboxGroup } from "@/admin/fields";
import { useAdminProblem } from "@/admin/problems";
import { listCandidates } from "@/candidates/api";
import { useIdempotencyKey } from "@/data/idempotency";
import { listTemplates } from "@/interviews/api";
import { listJobs } from "@/jobs/api";
import {
  type GenerateResult,
  generateQuestions,
  LEVELS,
  QUESTION_TYPES,
  type QuestionType,
} from "./api";
import { keys } from "./question-editor";

const NONE = "";
const CHOICES = 100;

/** Drafts questions with AI from PRD §23's inputs: the skills, the level, and optionally a job,
 * a candidate's work history and a template. The library's questions are sent too, so the AI
 * avoids repeating them. Every result is a draft until a recruiter approves it. */
export function GenerateDialog({
  onClose,
  onGenerated,
  canViewJobs = true,
  canViewCandidates = true,
  canViewTemplates = true,
}: {
  onClose: () => void;
  onGenerated: (result: GenerateResult) => void;
  canViewJobs?: boolean;
  canViewCandidates?: boolean;
  canViewTemplates?: boolean;
}) {
  const t = useTranslations("questions.generate");
  const labels = useTranslations("questions");
  const common = useTranslations("admin.common");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const [skills, setSkills] = useState("");
  const [count, setCount] = useState("5");
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("mid");
  const [jobId, setJobId] = useState(NONE);
  const [candidateId, setCandidateId] = useState(NONE);
  const [templateId, setTemplateId] = useState(NONE);
  const [types, setTypes] = useState<QuestionType[]>([]);
  const [tried, setTried] = useState(false);
  const key = useIdempotencyKey();
  const jobs = useQuery({
    queryKey: ["jobs", "list", "choices"],
    queryFn: () => listJobs({ limit: CHOICES }),
    enabled: canViewJobs,
  });
  const candidates = useQuery({
    queryKey: ["candidates", "list", "choices", jobId],
    queryFn: () => listCandidates({ limit: CHOICES, job_id: jobId || undefined }),
    enabled: canViewCandidates,
  });
  const templates = useQuery({
    queryKey: ["interview-templates", "list", "choices"],
    queryFn: () => listTemplates({ limit: CHOICES }),
    enabled: canViewTemplates,
  });

  const skillList = skills
    .split(",")
    .map((skill) => skill.trim())
    .filter(Boolean);
  const number = Number.parseInt(count, 10);
  const skillsOk = skillList.length >= 1 && skillList.length <= 10;
  const countOk = number >= 1 && number <= 10;

  const generate = useMutation({
    mutationFn: () =>
      generateQuestions(
        {
          skills: skillList,
          count: number,
          experience_level: level,
          job_id: jobId || null,
          candidate_id: candidateId || null,
          template_id: templateId || null,
          types,
        },
        key.current(),
      ),
    onSuccess: (result) => {
      key.renew();
      void queryClient.invalidateQueries({ queryKey: keys.list });
      toast.success(t("done", { count: result.drafts.length, skipped: result.skipped }), {});
      onGenerated(result);
    },
    onError: problems.show,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setTried(true);
    if (skillsOk && countOk) generate.mutate();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={t("title")}
        description={t("intro")}
        closeLabel={common("close")}
        className="max-h-[90vh] w-[min(40rem,calc(100vw-2rem))] overflow-y-auto"
      >
        <form noValidate onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-skills`}>{t("skills")}</Label>
            <Input
              id={`${id}-skills`}
              value={skills}
              placeholder={t("skillsPlaceholder")}
              aria-invalid={tried && !skillsOk}
              onChange={(event) => setSkills(event.target.value)}
            />
            {tried && !skillsOk ? (
              <p role="alert" className="text-danger text-xs">
                {t("skillsRequired")}
              </p>
            ) : null}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-count`}>{t("count")}</Label>
              <Input
                id={`${id}-count`}
                type="number"
                inputMode="numeric"
                min={1}
                max={10}
                value={count}
                aria-invalid={tried && !countOk}
                onChange={(event) => setCount(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-level`}>{t("level")}</Label>
              <NativeSelect
                id={`${id}-level`}
                value={level}
                onChange={(event) => setLevel(event.target.value as (typeof LEVELS)[number])}
                options={LEVELS.map((value) => ({ value, label: t(`levels.${value}`) }))}
              />
            </div>
            {canViewJobs ? (
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-job`}>{t("job")}</Label>
                <NativeSelect
                  id={`${id}-job`}
                  value={jobId}
                  onChange={(event) => {
                    setJobId(event.target.value);
                    setCandidateId(NONE);
                  }}
                  options={[
                    { value: NONE, label: t("none") },
                    ...(jobs.data?.items ?? []).map((job) => ({ value: job.id, label: job.title })),
                  ]}
                />
              </div>
            ) : null}
            {canViewCandidates ? (
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-candidate`}>{t("candidate")}</Label>
                <NativeSelect
                  id={`${id}-candidate`}
                  value={candidateId}
                  onChange={(event) => setCandidateId(event.target.value)}
                  options={[
                    { value: NONE, label: t("none") },
                    ...(candidates.data?.items ?? []).map((person) => ({
                      value: person.id,
                      label: person.name,
                    })),
                  ]}
                />
              </div>
            ) : null}
            {canViewTemplates ? (
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-template`}>{t("template")}</Label>
                <NativeSelect
                  id={`${id}-template`}
                  value={templateId}
                  onChange={(event) => setTemplateId(event.target.value)}
                  options={[
                    { value: NONE, label: t("none") },
                    ...(templates.data?.items ?? []).map((template) => ({
                      value: template.id,
                      label: template.name,
                    })),
                  ]}
                />
              </div>
            ) : null}
          </div>
          {canViewCandidates ? (
            <p id={`${id}-candidate-hint`} className="text-muted-foreground text-xs">
              {t("candidateHint")}
            </p>
          ) : null}
          <CheckboxGroup
            legend={t("types")}
            options={QUESTION_TYPES.map((type) => ({
              value: type,
              label: labels(`types.${type}`),
            }))}
            value={types}
            onChange={(next) => setTypes(next as QuestionType[])}
          />
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {common("cancel")}
            </Button>
            <Button type="submit" disabled={generate.isPending}>
              {generate.isPending ? t("working") : t("submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
