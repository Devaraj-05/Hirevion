"use client";

import { Badge, Button, Input, Label, Skeleton, Textarea, toast } from "@hirevion/ui";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { getQuestion, listQuestions } from "@/questions/api";
import {
  createTemplate,
  getInterviewDefaults,
  type MatrixPreview,
  type MatrixRow,
  previewSkillMatrix,
  type Template,
  updateTemplate,
} from "./api";
import {
  type Settings,
  SettingsFields,
  settingsBody,
  settingsOf,
  settingsProblems,
} from "./settings-fields";

export const keys = {
  all: ["interview-templates"] as const,
  list: ["interview-templates", "list"] as const,
  template: (id: string) => ["interview-templates", "detail", id] as const,
  versions: (id: string) => ["interview-templates", "detail", id, "versions"] as const,
  matrix: (id: string) => ["interview-templates", "detail", id, "matrix"] as const,
  defaults: ["interview-defaults"] as const,
};

const PREVIEW_DELAY_MS = 400;
const SEARCH_LIMIT = 8;

interface SkillRow {
  name: string;
  weight: string;
}
interface Pinned {
  question_id: string;
  version: number;
}

const whole = (text: string) => Number.parseInt(text, 10) || 0;

/** A template's own fields plus the shared settings. Without `template` it creates one
 * (starting from the organisation's defaults) and opens it; with one, every save is a new
 * version and earlier versions stay as they were (PRD §80). */
export function TemplateForm({ template, canManage }: { template?: Template; canManage: boolean }) {
  // The defaults also say what each proctoring level turns on.
  const defaults = useQuery({ queryKey: keys.defaults, queryFn: getInterviewDefaults });
  if (template) {
    return (
      <Editor
        key={`${template.id}-${template.version}`}
        template={template}
        start={settingsOf(template.current)}
        presets={defaults.data?.proctoring_presets}
        canManage={canManage && template.status === "active"}
      />
    );
  }
  if (!defaults.data) return <Skeleton className="h-96 w-full" />;
  return (
    <Editor
      start={settingsOf(defaults.data)}
      presets={defaults.data.proctoring_presets}
      canManage={canManage}
    />
  );
}

function Editor({
  template,
  start,
  presets,
  canManage,
}: {
  template?: Template;
  start: Settings;
  presets?: Record<string, string[]> | undefined;
  canManage: boolean;
}) {
  const t = useTranslations("interviews.templates");
  const problems = useAdminProblem();
  const router = useRouter();
  const queryClient = useQueryClient();
  const id = useId();
  const key = useRef(crypto.randomUUID());
  const [name, setName] = useState(template?.name ?? "");
  const [description, setDescription] = useState(template?.description ?? "");
  const [skills, setSkills] = useState<SkillRow[]>(() =>
    template
      ? template.current.skills.map((item) => ({
          name: String(item.name),
          weight: String(item.weight),
        }))
      : [{ name: "", weight: "100" }],
  );
  const [settings, setSettings] = useState(start);
  const [pinned, setPinned] = useState<Pinned[]>(
    () => (template?.current.questions ?? []) as unknown as Pinned[],
  );
  const [tried, setTried] = useState(false);

  const skillTotal = skills.reduce((sum, row) => sum + whole(row.weight), 0);
  const skillsOk =
    skills.length >= 1 &&
    skills.every((row) => row.name.trim() && whole(row.weight) >= 1) &&
    skillTotal === 100;
  const nameOk = name.trim().length > 0;
  const found = settingsProblems(settings);
  const pinnedOk = pinned.length <= whole(settings.question_count);
  const valid = nameOk && skillsOk && pinnedOk && Object.keys(found).length === 0;

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        description: description.trim(),
        skills: skills.map((row) => ({ name: row.name.trim(), weight: whole(row.weight) })),
        questions: pinned,
        ...settingsBody(settings),
      };
      return template ? updateTemplate(template.id, body) : createTemplate(body, key.current);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.template(saved.id), saved);
      void queryClient.invalidateQueries({ queryKey: keys.list });
      void queryClient.invalidateQueries({ queryKey: keys.versions(saved.id) });
      void queryClient.invalidateQueries({ queryKey: keys.matrix(saved.id) });
      if (template) toast.success(t("savedVersion", { version: saved.version }), {});
      else {
        toast.success(t("created"), {});
        router.push(`/interviews/templates/${saved.id}`);
      }
    },
    onError: problems.show,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setTried(true);
    if (valid) save.mutate();
  }

  const preview: MatrixPreview | null =
    skills.some((row) => row.name.trim()) &&
    whole(settings.question_count) >= 1 &&
    whole(settings.question_count) <= 50
      ? {
          question_count: whole(settings.question_count),
          skills: skills
            .filter((row) => row.name.trim() && whole(row.weight) >= 1)
            .map((row) => ({ name: row.name.trim(), weight: Math.min(whole(row.weight), 100) })),
          difficulty: {
            easy: whole(settings.difficulty.easy),
            medium: whole(settings.difficulty.medium),
            hard: whole(settings.difficulty.hard),
          },
        }
      : null;

  return (
    <form noValidate onSubmit={submit} className="grid gap-8">
      <fieldset disabled={!canManage} className="grid gap-4">
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-name`}>{t("name")}</Label>
          <Input
            id={`${id}-name`}
            value={name}
            aria-invalid={tried && !nameOk}
            onChange={(event) => setName(event.target.value)}
          />
          {tried && !nameOk ? (
            <p role="alert" className="text-danger text-xs">
              {t("nameRequired")}
            </p>
          ) : null}
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-description`}>{t("description")}</Label>
          <Textarea
            id={`${id}-description`}
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <fieldset className="grid gap-2">
          <legend className="mb-1 font-medium text-sm">{t("skills")}</legend>
          {skills.map((row, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows have no identity while edited
            <div key={index} className="flex items-end gap-2">
              <div className="grid flex-1 gap-1">
                <Label htmlFor={`${id}-skill-${index}`} className="sr-only">
                  {t("skillName", { number: index + 1 })}
                </Label>
                <Input
                  id={`${id}-skill-${index}`}
                  placeholder={t("skillPlaceholder")}
                  value={row.name}
                  onChange={(event) =>
                    setSkills(
                      skills.map((item, at) =>
                        at === index ? { ...item, name: event.target.value } : item,
                      ),
                    )
                  }
                />
              </div>
              <div className="grid w-24 gap-1">
                <Label htmlFor={`${id}-skill-weight-${index}`} className="sr-only">
                  {t("skillWeight", { number: index + 1 })}
                </Label>
                <Input
                  id={`${id}-skill-weight-${index}`}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={100}
                  value={row.weight}
                  onChange={(event) =>
                    setSkills(
                      skills.map((item, at) =>
                        at === index ? { ...item, weight: event.target.value } : item,
                      ),
                    )
                  }
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                aria-label={t("removeSkill", { number: index + 1 })}
                disabled={skills.length === 1}
                onClick={() => setSkills(skills.filter((_, at) => at !== index))}
              >
                <X className="size-4" aria-hidden />
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-3">
            {skills.length < 20 ? (
              <Button
                type="button"
                variant="secondary"
                className="w-fit"
                onClick={() => setSkills([...skills, { name: "", weight: "" }])}
              >
                <Plus className="size-4" aria-hidden />
                {t("addSkill")}
              </Button>
            ) : null}
            <span className="text-muted-foreground text-sm">
              {t("skillTotal", { total: skillTotal })}
            </span>
          </div>
          {tried && !skillsOk ? (
            <p role="alert" className="text-danger text-xs">
              {t("skillsWrong", { total: skillTotal })}
            </p>
          ) : null}
        </fieldset>
      </fieldset>

      <SettingsFields
        value={settings}
        onChange={setSettings}
        showProblems={tried}
        presets={presets}
        readOnly={!canManage}
      />

      <PinnedQuestions
        pinned={pinned}
        onChange={setPinned}
        readOnly={!canManage}
        error={
          tried && !pinnedOk ? t("tooManyPinned", { count: whole(settings.question_count) }) : null
        }
      />

      <MatrixPreviewPanel preview={preview} />

      {canManage ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={save.isPending}>
            {template ? t("saveVersion", { version: template.version + 1 }) : t("create")}
          </Button>
          {template ? (
            <span className="text-muted-foreground text-sm">{t("versionHint")}</span>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}

/** Approved library questions the template always asks (each pinned at its current version). */
function PinnedQuestions({
  pinned,
  onChange,
  readOnly,
  error,
}: {
  pinned: Pinned[];
  onChange: (next: Pinned[]) => void;
  readOnly: boolean;
  error: string | null;
}) {
  const t = useTranslations("interviews.templates");
  const id = useId();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);
  const found = useQuery({
    queryKey: ["questions", "list", "pin", query],
    queryFn: () =>
      listQuestions({ status: "approved", q: query || undefined, limit: SEARCH_LIMIT }),
    enabled: !readOnly,
  });
  const details = useQueries({
    queries: pinned.map((item) => ({
      queryKey: ["questions", "detail", item.question_id],
      queryFn: () => getQuestion(item.question_id),
      staleTime: 60_000,
    })),
  });
  const taken = new Set(pinned.map((item) => item.question_id));

  return (
    <section className="grid gap-3" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="font-medium text-sm">
        {t("pinned")}
      </h2>
      <p className="text-muted-foreground text-xs">{t("pinnedHint")}</p>
      {pinned.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("nonePinned")}</p>
      ) : (
        <ul className="grid gap-2">
          {pinned.map((item, index) => {
            const detail = details[index]?.data;
            return (
              <li
                key={item.question_id}
                className="flex items-start justify-between gap-2 rounded-md border border-border p-2 text-sm"
              >
                <span className="grid gap-0.5">
                  <span className="line-clamp-2">{detail?.text ?? t("loadingQuestion")}</span>
                  <span className="text-muted-foreground text-xs">
                    {t("pinnedVersion", { version: item.version })}
                    {detail && detail.version !== item.version
                      ? ` · ${t("newerVersion", { version: detail.version })}`
                      : ""}
                  </span>
                </span>
                {readOnly ? null : (
                  <Button
                    type="button"
                    variant="ghost"
                    aria-label={t("unpin")}
                    onClick={() =>
                      onChange(pinned.filter((other) => other.question_id !== item.question_id))
                    }
                  >
                    <X className="size-4" aria-hidden />
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {readOnly ? null : (
        <div className="grid gap-2">
          <Label htmlFor={`${id}-search`}>{t("findQuestion")}</Label>
          <Input
            id={`${id}-search`}
            type="search"
            value={text}
            placeholder={t("findPlaceholder")}
            onChange={(event) => setText(event.target.value)}
          />
          <ul className="grid gap-1" aria-label={t("results")}>
            {(found.data?.items ?? [])
              .filter((question) => !taken.has(question.id))
              .map((question) => (
                <li key={question.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="line-clamp-1">
                    {question.text}{" "}
                    <span className="text-muted-foreground">{`· ${question.skill_name}`}</span>
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      onChange([...pinned, { question_id: question.id, version: question.version }])
                    }
                  >
                    {t("pin")}
                  </Button>
                </li>
              ))}
          </ul>
        </div>
      )}
      {error ? (
        <p role="alert" className="text-danger text-xs">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function MatrixPreviewPanel({ preview }: { preview: MatrixPreview | null }) {
  const [settled, setSettled] = useState(preview);
  const serialised = JSON.stringify(preview);
  useEffect(() => {
    const timer = setTimeout(
      () => setSettled(JSON.parse(serialised) as MatrixPreview | null),
      PREVIEW_DELAY_MS,
    );
    return () => clearTimeout(timer);
  }, [serialised]);
  const rows = useQuery({
    queryKey: ["interview-templates", "matrix-preview", settled],
    queryFn: () => previewSkillMatrix(settled as MatrixPreview),
    enabled: settled !== null && settled.skills.length > 0,
  });
  return <MatrixTable rows={rows.data} pending={rows.isFetching && !rows.data} />;
}

/** The skill matrix (PRD §34): each skill's questions by difficulty, against the approved
 * library questions available; shortfalls show before any interview is scheduled. */
export function MatrixTable({
  rows,
  pending = false,
}: {
  rows: MatrixRow[] | undefined;
  pending?: boolean;
}) {
  const t = useTranslations("interviews.matrix");
  const questions = useTranslations("questions");
  const levels = ["easy", "medium", "hard"] as const;
  return (
    <section className="grid gap-2">
      <h2 className="font-medium text-sm">{t("title")}</h2>
      <p className="text-muted-foreground text-xs">{t("intro")}</p>
      {pending ? <Skeleton className="h-24 w-full" /> : null}
      {rows && rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("title")}</caption>
            <thead>
              <tr className="border-border border-b text-left text-muted-foreground">
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("skill")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("weight")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("questions")}
                </th>
                {levels.map((level) => (
                  <th key={level} scope="col" className="py-1 pr-3 font-medium">
                    {questions(`difficulties.${level}`)}
                  </th>
                ))}
                <th scope="col" className="py-1 font-medium">
                  {t("library")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const short = Object.values(row.gaps).reduce((sum, gap) => sum + gap, 0);
                return (
                  <tr key={row.skill} className="border-border border-b last:border-0">
                    <th scope="row" className="py-1 pr-3 text-left font-medium">
                      {row.skill}
                    </th>
                    <td className="py-1 pr-3">{t("percent", { weight: row.weight })}</td>
                    <td className="py-1 pr-3">{row.questions}</td>
                    {levels.map((level) => (
                      <td key={level} className="py-1 pr-3">
                        {t("ofAvailable", {
                          needed: row.by_difficulty[level] ?? 0,
                          available: row.available[level] ?? 0,
                        })}
                      </td>
                    ))}
                    <td className="py-1">
                      {short > 0 ? (
                        <Badge tone="warning">{t("short", { count: short })}</Badge>
                      ) : (
                        <Badge tone="success">{t("covered")}</Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : pending ? null : (
        <p className="text-muted-foreground text-sm">{t("empty")}</p>
      )}
    </section>
  );
}
