"use client";

import {
  Badge,
  Button,
  Input,
  Label,
  NativeSelect,
  Sheet,
  SheetContent,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { CheckboxGroup } from "@/admin/fields";
import { useAdminProblem } from "@/admin/problems";
import {
  approveQuestion,
  archiveQuestion,
  CATEGORIES,
  type Category,
  CODING_LANGUAGES,
  type CodingLanguage,
  createQuestion,
  DIFFICULTIES,
  type Difficulty,
  getQuestion,
  listQuestionVersions,
  QUESTION_TYPES,
  type Question,
  type QuestionBody,
  type QuestionType,
  restoreQuestion,
  updateQuestion,
} from "./api";

export const keys = {
  all: ["questions"] as const,
  list: ["questions", "list"] as const,
  question: (id: string) => ["questions", "detail", id] as const,
  versions: (id: string) => ["questions", "detail", id, "versions"] as const,
};

export const STATUS_TONES = { draft: "warning", approved: "success", archived: "neutral" } as const;
const FOLLOW_UPS = ["strong", "partial", "weak"] as const;
type FollowUp = (typeof FOLLOW_UPS)[number];
const FROM_TYPE = "";

interface Draft {
  text: string;
  skill_name: string;
  topic: string;
  type: QuestionType;
  category: Category | typeof FROM_TYPE;
  difficulty: Difficulty;
  time_limit: string;
  concepts: string;
  rubric: { criterion: string; weight: string }[];
  follow_ups: Record<FollowUp, string>;
  languages: CodingLanguage[];
}

function draftOf(question: Question | undefined): Draft {
  const prompts = Object.fromEntries(FOLLOW_UPS.map((when) => [when, ""])) as Record<
    FollowUp,
    string
  >;
  for (const rule of question?.follow_up_rules ?? []) {
    const when = rule.when as FollowUp;
    if (FOLLOW_UPS.includes(when)) prompts[when] = String(rule.prompt ?? "");
  }
  const languages = (question?.coding?.languages as CodingLanguage[] | undefined) ?? ["python"];
  return {
    text: question?.text ?? "",
    skill_name: question?.skill_name ?? "",
    topic: question?.topic ?? "",
    type: question?.type ?? "technical",
    category: question?.category ?? FROM_TYPE,
    difficulty: question?.difficulty ?? "medium",
    time_limit: question?.time_limit_seconds ? String(question.time_limit_seconds) : "",
    concepts: (question?.expected_concepts ?? []).join("\n"),
    rubric: (question?.rubric ?? []).map((item) => ({
      criterion: String(item.criterion ?? ""),
      weight: String(item.weight ?? ""),
    })),
    follow_ups: prompts,
    languages,
  };
}

/** What's wrong with a draft, by field; empty when it can be saved. */
export function problemsOf(
  draft: Draft,
): Partial<Record<"text" | "skill" | "rubric" | "time", string>> {
  const found: Partial<Record<"text" | "skill" | "rubric" | "time", string>> = {};
  if (draft.text.trim().length < 10) found.text = "textTooShort";
  if (!draft.skill_name.trim()) found.skill = "skillRequired";
  const time = draft.time_limit.trim();
  if (time && !(Number(time) >= 30 && Number(time) <= 3600)) found.time = "timeRange";
  if (draft.rubric.length > 0) {
    const total = draft.rubric.reduce(
      (sum, row) => sum + (Number.parseInt(row.weight, 10) || 0),
      0,
    );
    if (total !== 100 || draft.rubric.some((row) => !row.criterion.trim()))
      found.rubric = "rubricTotal";
  }
  return found;
}

function bodyOf(draft: Draft): QuestionBody {
  return {
    text: draft.text.trim(),
    skill_name: draft.skill_name.trim(),
    topic: draft.topic.trim() || null,
    type: draft.type,
    category: draft.category === FROM_TYPE ? null : draft.category,
    difficulty: draft.difficulty,
    time_limit_seconds: draft.time_limit.trim() ? Number(draft.time_limit) : null,
    expected_concepts: draft.concepts
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
    rubric: draft.rubric.map((row) => ({
      criterion: row.criterion.trim(),
      weight: Number.parseInt(row.weight, 10) || 0,
      description: "",
    })),
    follow_up_rules: FOLLOW_UPS.filter((when) => draft.follow_ups[when].trim()).map((when) => ({
      when,
      prompt: draft.follow_ups[when].trim(),
    })),
    coding: draft.type === "coding" ? { languages: draft.languages, starter_code: {} } : null,
  };
}

/** A question in a sheet: a new one (`questionId` null) or an existing one with its versions,
 * approval and archiving. Every save of an existing question is a new version (PRD §80). */
export function QuestionEditor({
  questionId,
  canManage,
  onClose,
}: {
  questionId: string | null;
  canManage: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("questions.editor");
  const common = useTranslations("admin.common");
  const question = useQuery({
    queryKey: keys.question(questionId ?? "new"),
    queryFn: () => getQuestion(questionId as string),
    enabled: questionId !== null,
  });
  const title = questionId === null ? t("newTitle") : t("editTitle");
  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent title={title} closeLabel={common("close")} className="w-[min(40rem,100vw)]">
        {questionId === null ? (
          <QuestionForm canManage={canManage} onDone={onClose} />
        ) : question.data ? (
          <QuestionForm
            key={`${question.data.id}-${question.data.version}-${question.data.status}`}
            question={question.data}
            canManage={canManage}
            onDone={onClose}
          />
        ) : question.isError ? (
          <p role="alert" className="text-danger text-sm">
            {common("loadFailed")}
          </p>
        ) : (
          <Skeleton className="h-96 w-full" />
        )}
      </SheetContent>
    </Sheet>
  );
}

function QuestionForm({
  question,
  canManage,
  onDone,
}: {
  question?: Question;
  canManage: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("questions");
  const format = useFormatter();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const key = useRef(crypto.randomUUID());
  const [draft, setDraft] = useState(() => draftOf(question));
  const [tried, setTried] = useState(false);
  const found = problemsOf(draft);
  const valid = Object.keys(found).length === 0;
  const readOnly = !canManage || question?.status === "archived";

  function set<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft((previous) => ({ ...previous, [field]: value }));
  }

  function changed(saved: Question) {
    queryClient.setQueryData(keys.question(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: keys.list });
    void queryClient.invalidateQueries({ queryKey: keys.versions(saved.id) });
  }

  const save = useMutation({
    mutationFn: (status: "draft" | "approved") =>
      question
        ? updateQuestion(question.id, bodyOf(draft))
        : createQuestion({ ...bodyOf(draft), status }, key.current),
    onSuccess: (saved) => {
      changed(saved);
      toast.success(
        question ? t("editor.savedVersion", { version: saved.version }) : t("editor.created"),
        {},
      );
      if (!question) onDone();
    },
    onError: problems.show,
  });
  const move = useMutation({
    mutationFn: (action: "approve" | "archive" | "restore") => {
      const target = question as Question;
      if (action === "approve") return approveQuestion(target.id);
      if (action === "archive") return archiveQuestion(target.id);
      return restoreQuestion(target.id);
    },
    onSuccess: (saved, action) => {
      changed(saved);
      toast.success(t(`editor.${action}d`), {});
    },
    onError: problems.show,
  });

  function submit(
    event: { preventDefault: () => void },
    status: "draft" | "approved" = "approved",
  ) {
    event.preventDefault();
    setTried(true);
    if (valid) save.mutate(status);
  }

  const error = (field: keyof typeof found) =>
    tried && found[field] ? (
      <p role="alert" className="text-danger text-xs">
        {t(`editor.${found[field]}` as "editor.textTooShort")}
      </p>
    ) : null;
  const rubricTotal = draft.rubric.reduce(
    (sum, row) => sum + (Number.parseInt(row.weight, 10) || 0),
    0,
  );

  return (
    <form noValidate onSubmit={(event) => submit(event)} className="flex flex-col gap-5">
      {question ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={STATUS_TONES[question.status]}>{t(`statuses.${question.status}`)}</Badge>
          {question.source === "ai" ? <Badge tone="info">{t("aiDraft")}</Badge> : null}
          <span className="text-muted-foreground">
            {t("editor.version", { version: question.version })}
          </span>
          {question.status === "draft" ? (
            <span className="text-muted-foreground">{t("editor.draftHint")}</span>
          ) : null}
        </div>
      ) : null}
      <fieldset disabled={readOnly} className="grid gap-4">
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-text`}>{t("fields.text")}</Label>
          <Textarea
            id={`${id}-text`}
            rows={4}
            value={draft.text}
            aria-invalid={tried && Boolean(found.text)}
            onChange={(event) => set("text", event.target.value)}
          />
          {error("text")}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-skill`}>{t("fields.skill")}</Label>
            <Input
              id={`${id}-skill`}
              value={draft.skill_name}
              aria-invalid={tried && Boolean(found.skill)}
              onChange={(event) => set("skill_name", event.target.value)}
            />
            {error("skill")}
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-topic`}>{t("fields.topic")}</Label>
            <Input
              id={`${id}-topic`}
              value={draft.topic}
              onChange={(event) => set("topic", event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-type`}>{t("fields.type")}</Label>
            <NativeSelect
              id={`${id}-type`}
              value={draft.type}
              onChange={(event) => set("type", event.target.value as QuestionType)}
              options={QUESTION_TYPES.map((type) => ({ value: type, label: t(`types.${type}`) }))}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-category`}>{t("fields.category")}</Label>
            <NativeSelect
              id={`${id}-category`}
              value={draft.category}
              onChange={(event) => set("category", event.target.value as Category)}
              options={[
                { value: FROM_TYPE, label: t("editor.categoryFromType") },
                ...CATEGORIES.map((category) => ({
                  value: category,
                  label: t(`categories.${category}`),
                })),
              ]}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-difficulty`}>{t("fields.difficulty")}</Label>
            <NativeSelect
              id={`${id}-difficulty`}
              value={draft.difficulty}
              onChange={(event) => set("difficulty", event.target.value as Difficulty)}
              options={DIFFICULTIES.map((level) => ({
                value: level,
                label: t(`difficulties.${level}`),
              }))}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-time`}>{t("fields.timeLimit")}</Label>
            <Input
              id={`${id}-time`}
              type="number"
              inputMode="numeric"
              min={30}
              max={3600}
              value={draft.time_limit}
              aria-invalid={tried && Boolean(found.time)}
              onChange={(event) => set("time_limit", event.target.value)}
            />
            {error("time")}
          </div>
        </div>
        {draft.type === "coding" ? (
          <CheckboxGroup
            legend={t("fields.languages")}
            options={CODING_LANGUAGES.map((language) => ({
              value: language,
              label: t(`languages.${language}`),
            }))}
            value={draft.languages}
            onChange={(languages) => set("languages", languages as CodingLanguage[])}
          />
        ) : null}
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-concepts`}>{t("fields.concepts")}</Label>
          <Textarea
            id={`${id}-concepts`}
            rows={3}
            value={draft.concepts}
            aria-describedby={`${id}-concepts-hint`}
            onChange={(event) => set("concepts", event.target.value)}
          />
          <p id={`${id}-concepts-hint`} className="text-muted-foreground text-xs">
            {t("editor.onePerLine")}
          </p>
        </div>
        <fieldset className="grid gap-2">
          <legend className="mb-1 font-medium text-sm">{t("fields.rubric")}</legend>
          {draft.rubric.map((row, index) => (
            // Rows have no identity of their own; their position is their key while editing.
            // biome-ignore lint/suspicious/noArrayIndexKey: see above
            <div key={index} className="flex items-end gap-2">
              <div className="grid flex-1 gap-1">
                <Label htmlFor={`${id}-criterion-${index}`} className="sr-only">
                  {t("editor.criterion", { number: index + 1 })}
                </Label>
                <Input
                  id={`${id}-criterion-${index}`}
                  placeholder={t("editor.criterionPlaceholder")}
                  value={row.criterion}
                  onChange={(event) =>
                    set(
                      "rubric",
                      draft.rubric.map((item, at) =>
                        at === index ? { ...item, criterion: event.target.value } : item,
                      ),
                    )
                  }
                />
              </div>
              <div className="grid w-24 gap-1">
                <Label htmlFor={`${id}-weight-${index}`} className="sr-only">
                  {t("editor.weight", { number: index + 1 })}
                </Label>
                <Input
                  id={`${id}-weight-${index}`}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={100}
                  value={row.weight}
                  onChange={(event) =>
                    set(
                      "rubric",
                      draft.rubric.map((item, at) =>
                        at === index ? { ...item, weight: event.target.value } : item,
                      ),
                    )
                  }
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                aria-label={t("editor.removeCriterion", { number: index + 1 })}
                onClick={() =>
                  set(
                    "rubric",
                    draft.rubric.filter((_, at) => at !== index),
                  )
                }
              >
                <X className="size-4" aria-hidden />
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-3">
            {draft.rubric.length < 10 ? (
              <Button
                type="button"
                variant="secondary"
                className="w-fit"
                onClick={() => set("rubric", [...draft.rubric, { criterion: "", weight: "" }])}
              >
                <Plus className="size-4" aria-hidden />
                {t("editor.addCriterion")}
              </Button>
            ) : null}
            {draft.rubric.length > 0 ? (
              <span className="text-muted-foreground text-sm">
                {t("editor.rubricTotalNow", { total: rubricTotal })}
              </span>
            ) : null}
          </div>
          {error("rubric")}
        </fieldset>
        <fieldset className="grid gap-3">
          <legend className="mb-1 font-medium text-sm">{t("fields.followUps")}</legend>
          {FOLLOW_UPS.map((when) => (
            <div key={when} className="grid gap-1">
              <Label htmlFor={`${id}-follow-${when}`}>{t(`followUps.${when}`)}</Label>
              <Input
                id={`${id}-follow-${when}`}
                value={draft.follow_ups[when]}
                onChange={(event) =>
                  set("follow_ups", { ...draft.follow_ups, [when]: event.target.value })
                }
              />
            </div>
          ))}
        </fieldset>
      </fieldset>
      {canManage ? (
        <div className="flex flex-wrap gap-2 border-border border-t pt-4">
          {question?.status === "archived" ? (
            <Button type="button" disabled={move.isPending} onClick={() => move.mutate("restore")}>
              {t("editor.restore")}
            </Button>
          ) : (
            <>
              <Button type="submit" disabled={save.isPending}>
                {question ? t("editor.saveVersion") : t("editor.saveApproved")}
              </Button>
              {question ? null : (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={save.isPending}
                  onClick={(event) => submit(event, "draft")}
                >
                  {t("editor.saveDraft")}
                </Button>
              )}
              {question?.status === "draft" ? (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={move.isPending}
                  onClick={() => move.mutate("approve")}
                >
                  {t("editor.approve")}
                </Button>
              ) : null}
              {question ? (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={move.isPending}
                  onClick={() => move.mutate("archive")}
                >
                  {t("editor.archive")}
                </Button>
              ) : null}
            </>
          )}
        </div>
      ) : null}
      {question ? <Versions questionId={question.id} format={format} /> : null}
    </form>
  );
}

function Versions({
  questionId,
  format,
}: {
  questionId: string;
  format: ReturnType<typeof useFormatter>;
}) {
  const t = useTranslations("questions.editor");
  const versions = useQuery({
    queryKey: keys.versions(questionId),
    queryFn: () => listQuestionVersions(questionId),
  });
  if (!versions.data) return null;
  return (
    <section className="grid gap-2 border-border border-t pt-4" aria-label={t("versions")}>
      <h3 className="font-medium text-sm">{t("versions")}</h3>
      <ol className="grid gap-2">
        {[...versions.data].reverse().map((version) => (
          <li key={version.version} className="grid gap-0.5 text-sm">
            <span className="text-muted-foreground text-xs">
              {t("versionLine", {
                version: version.version,
                date: format.dateTime(new Date(version.created_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </span>
            <span className="line-clamp-2">{version.text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
