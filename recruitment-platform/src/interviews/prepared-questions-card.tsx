"use client";

import {
  Badge,
  type BadgeTone,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@hirevion/ui";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { getQuestionPlan, interviewKeys, type QuestionPlan } from "./assigned-api";

type PlannedQuestion = QuestionPlan["questions"][number];

const LEVELS = ["easy", "medium", "hard"] as const;
type Level = (typeof LEVELS)[number];
const isLevel = (value: string): value is Level => (LEVELS as readonly string[]).includes(value);
const LEVEL_TONES: Record<Level, BadgeTone> = { easy: "neutral", medium: "info", hard: "warning" };

/** The questions prepared for the interview from the job and the resume (C8-10, owner
 * 2026-11-22: "a read-only list"), by skill, each with its level and where it comes from.
 * Recruiters see them; candidates never do. */
export function PreparedQuestionsCard({ id }: { id: string }) {
  const t = useTranslations("interviews.assigned.prepared");
  const plan = useQuery({
    queryKey: [...interviewKeys.detail(id), "question-plan"],
    queryFn: () => getQuestionPlan(id),
    // The worker takes a little while: look again until the questions are ready.
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 5_000 : false),
  });
  const bySkill = new Map<string, PlannedQuestion[]>();
  for (const question of plan.data?.questions ?? []) {
    bySkill.set(question.skill, [...(bySkill.get(question.skill) ?? []), question]);
  }
  const source = (question: PlannedQuestion) =>
    question.source === "resume" && question.quote
      ? t("fromResume", { quote: question.quote })
      : question.source === "library"
        ? t("fromLibrary")
        : t("fromJob");

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        {plan.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : plan.isError ? (
          <p className="text-muted-foreground text-sm">{t("unavailable")}</p>
        ) : plan.data.status === "pending" ? (
          <p className="text-muted-foreground text-sm">{t("pending")}</p>
        ) : plan.data.status === "failed" ? (
          <p className="text-muted-foreground text-sm">{t("failed")}</p>
        ) : (
          <>
            <p className="text-muted-foreground text-sm">
              {t("lead", { count: plan.data.questions.length })}
            </p>
            {[...bySkill.entries()].map(([skill, questions]) => (
              <section key={skill} className="grid gap-2">
                <h3 className="font-medium text-sm">{skill}</h3>
                <ol className="grid gap-2">
                  {questions.map((question) => (
                    <li key={question.text} className="grid gap-1 rounded-md border p-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        {isLevel(question.difficulty) ? (
                          <Badge tone={LEVEL_TONES[question.difficulty]}>
                            {t(`levels.${question.difficulty}`)}
                          </Badge>
                        ) : null}
                        {question.concept ? (
                          <span className="text-muted-foreground">{question.concept}</span>
                        ) : null}
                      </div>
                      <p>{question.text}</p>
                      <p className="text-muted-foreground text-xs">{source(question)}</p>
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          </>
        )}
      </CardContent>
    </Card>
  );
}
