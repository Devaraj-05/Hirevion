"use client";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import {
  type EvaluationBody,
  type EvaluationEvidence,
  evaluationKeys,
  getCalibration,
  getEvaluation,
  getQuestionEvaluation,
  listMyScores,
  type QuestionEvaluationBrief,
  queueRerun,
  saveMyScores,
} from "./evaluation-api";
import {
  agreementLevel,
  clock,
  DIMENSIONS,
  type Dimension,
  draftFrom,
  formatScore,
  gaps,
  mergeScores,
  type ScoreDraft,
  summaryRevealed,
  validateScores,
} from "./evaluation-model";

const POLL_MS = 5000;

function Quotes({ items }: { items: EvaluationEvidence[] }) {
  const t = useTranslations("interviews.evaluation");
  if (items.length === 0) return <p className="text-muted-foreground text-xs">{t("noQuote")}</p>;
  return (
    <ul className="grid gap-1 text-xs">
      {items.map((item) => (
        <li key={`${item.seq}-${item.quote}`} className="text-muted-foreground">
          <span className="tabular-nums">{clock(item.start_ms)}</span>
          {` “${item.quote}”`}
        </li>
      ))}
    </ul>
  );
}

function SupportBadge({ supported }: { supported: boolean }) {
  const t = useTranslations("interviews.evaluation");
  return (
    <Badge tone={supported ? "success" : "warning"}>
      {supported ? t("supported") : t("unsupported")}
    </Badge>
  );
}

function Findings({
  title,
  items,
}: {
  title: string;
  items: {
    text: string;
    skill: string | null;
    evidence: EvaluationEvidence[];
    supported: boolean;
  }[];
}) {
  const t = useTranslations("interviews.evaluation");
  return (
    <section className="grid gap-2">
      <h3 className="font-medium text-sm">{title}</h3>
      {items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noneListed")}</p>
      ) : (
        <ul className="grid gap-3 text-sm">
          {items.map((item) => (
            <li key={item.text} className="grid gap-1">
              <p>
                {item.skill ? <Badge className="mr-2">{item.skill}</Badge> : null}
                {item.text}
              </p>
              <Quotes items={item.evidence} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Summary({ evaluation }: { evaluation: EvaluationBody }) {
  const t = useTranslations("interviews.evaluation");
  const follow = evaluation.follow_up_performance;
  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <p>
          <span className="text-muted-foreground text-sm">{t("overall")}</span>{" "}
          <span className="font-semibold text-2xl tabular-nums">
            {formatScore(evaluation.overall_score)}
          </span>
        </p>
        <p className="text-sm">
          <span className="text-muted-foreground">{t("communication")}</span>{" "}
          <span className="font-medium tabular-nums">
            {formatScore(evaluation.communication.score)}
          </span>
        </p>
        <p className="text-muted-foreground text-sm">{t("codingPending")}</p>
      </div>
      <section className="grid gap-2">
        <h3 className="font-medium text-sm">{t("skills")}</h3>
        <ul className="grid gap-3">
          {evaluation.skills.map((skill) => (
            <li key={skill.skill} className="grid gap-1 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{skill.skill}</span>
                <span className="tabular-nums">
                  {skill.score === null ? t("notAssessed") : formatScore(skill.score)}
                </span>
                {skill.score !== null ? <SupportBadge supported={skill.supported} /> : null}
                <span className="text-muted-foreground">
                  {t("questionCount", { count: skill.questions })}
                </span>
              </p>
              {skill.evidence.length > 0 ? <Quotes items={skill.evidence.slice(0, 2)} /> : null}
            </li>
          ))}
        </ul>
      </section>
      <div className="grid gap-5 md:grid-cols-2">
        <Findings title={t("strengths")} items={evaluation.strengths} />
        <Findings title={t("gaps")} items={evaluation.knowledge_gaps} />
      </div>
      <section className="grid gap-1 text-sm">
        <h3 className="font-medium">{t("followUps")}</h3>
        {follow.asked === 0 ? (
          <p className="text-muted-foreground">{t("noFollowUps")}</p>
        ) : (
          <>
            <p>
              {t("followUpLine", {
                asked: follow.asked,
                mean: formatScore(follow.mean),
                main: formatScore(follow.main_mean),
              })}
            </p>
            {follow.summary.summary ? <p>{follow.summary.summary}</p> : null}
            <Quotes items={follow.summary.evidence} />
          </>
        )}
      </section>
      {evaluation.flags.length > 0 ? (
        <p className="text-muted-foreground text-xs">
          {t("flags", { flags: evaluation.flags.join(", ") })}
        </p>
      ) : null}
      <p className="text-muted-foreground text-xs">
        {t("versions", {
          model: evaluation.versions.model ?? "–",
          prompt: evaluation.versions.prompt,
          rubric: evaluation.versions.rubric,
          evaluation: evaluation.versions.evaluation,
        })}
      </p>
    </div>
  );
}

function Revealed({
  interviewId,
  question,
  own,
}: {
  interviewId: string;
  question: QuestionEvaluationBrief;
  own: Partial<Record<string, number>>;
}) {
  const t = useTranslations("interviews.evaluation");
  const detail = useQuery({
    queryKey: evaluationKeys.question(interviewId, question.question_id),
    queryFn: () => getQuestionEvaluation(interviewId, question.question_id),
  });
  if (detail.isPending) return <Skeleton className="h-24 w-full" />;
  if (detail.isError) {
    return (
      <p className="text-sm" role="alert">
        {t("loadFailed")}
      </p>
    );
  }
  const difference = gaps(question.scores, own);
  return (
    <div className="grid gap-3">
      <table className="w-full text-left text-sm">
        <thead className="text-muted-foreground text-xs">
          <tr>
            <th className="py-1 pr-2 font-normal">{t("dimension")}</th>
            <th className="py-1 pr-2 font-normal">{t("yourScore")}</th>
            <th className="py-1 pr-2 font-normal">{t("aiScore")}</th>
            <th className="py-1 font-normal">{t("difference")}</th>
          </tr>
        </thead>
        <tbody>
          {detail.data.dimensions.map((dimension) => {
            const diff = difference[dimension.dimension as Dimension];
            return (
              <tr key={dimension.dimension} className="align-top">
                <td className="py-1 pr-2">
                  {t(`dimensions.${dimension.dimension as Dimension}`)}
                  <Quotes items={dimension.evidence.slice(0, 1)} />
                </td>
                <td className="py-1 pr-2 tabular-nums">{formatScore(own[dimension.dimension])}</td>
                <td className="py-1 pr-2 tabular-nums">
                  {formatScore(dimension.score)}
                  {dimension.supported ? null : (
                    <span className="block text-muted-foreground text-xs">{t("capped")}</span>
                  )}
                </td>
                <td className="py-1 tabular-nums">
                  {diff === undefined ? "–" : `${diff > 0 ? "+" : ""}${diff}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {detail.data.missing_concepts.length > 0 ? (
        <p className="text-sm">
          {t("missing", { concepts: detail.data.missing_concepts.join(", ") })}
        </p>
      ) : null}
      {detail.data.note ? (
        <p className="text-muted-foreground text-sm">{detail.data.note}</p>
      ) : null}
    </div>
  );
}

function QuestionPanel({
  interviewId,
  question,
  saved,
}: {
  interviewId: string;
  question: QuestionEvaluationBrief;
  saved: { dimensions: Record<string, number>; note: string } | undefined;
}) {
  const t = useTranslations("interviews.evaluation");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const id = useId();
  const [draft, setDraft] = useState<ScoreDraft>(() => draftFrom(saved?.dimensions));
  const [note, setNote] = useState(saved?.note ?? "");
  const checked = validateScores(draft);
  const save = useMutation({
    mutationFn: () =>
      saveMyScores(
        interviewId,
        question.question_id,
        mergeScores(saved?.dimensions, checked.scores),
        note,
      ),
    onSuccess: () => {
      toast.success(t("saved"), {});
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.mine(interviewId) });
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.calibration });
    },
    onError: problems.show,
  });
  return (
    <details className="rounded-md border p-3">
      <summary className="cursor-pointer text-sm">
        <span className="text-muted-foreground tabular-nums">{`${question.position}. `}</span>
        {question.text}
        {saved ? <Badge className="ml-2">{t("youScored")}</Badge> : null}
      </summary>
      <div className="mt-3 grid gap-4">
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm">{t("yourScores")}</legend>
          {saved === undefined ? (
            <p className="text-muted-foreground text-xs">{t("blindFirst")}</p>
          ) : null}
          <div className="grid gap-2 sm:grid-cols-2">
            {DIMENSIONS.map((dimension) => (
              <div key={dimension} className="grid gap-1">
                <Label htmlFor={`${id}-${dimension}`}>{t(`dimensions.${dimension}`)}</Label>
                <Input
                  id={`${id}-${dimension}`}
                  inputMode="decimal"
                  value={draft[dimension] ?? ""}
                  aria-invalid={checked.errors[dimension] !== undefined}
                  onChange={(event) => setDraft({ ...draft, [dimension]: event.target.value })}
                />
                {checked.errors[dimension] ? (
                  <p className="text-xs" role="alert">
                    {t(`errors.${checked.errors[dimension]}`)}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
          <div className="grid gap-1">
            <Label htmlFor={`${id}-note`}>{t("note")}</Label>
            <Textarea
              id={`${id}-note`}
              value={note}
              maxLength={1000}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <div>
            <Button
              size="sm"
              disabled={!checked.ok || save.isPending}
              onClick={() => save.mutate()}
            >
              {t("save")}
            </Button>
          </div>
        </fieldset>
        {saved ? (
          <Revealed interviewId={interviewId} question={question} own={saved.dimensions} />
        ) : null}
      </div>
    </details>
  );
}

function Agreement() {
  const t = useTranslations("interviews.evaluation.agreement");
  const stats = useQuery({ queryKey: evaluationKeys.calibration, queryFn: getCalibration });
  if (stats.isPending) return <Skeleton className="h-16 w-full" />;
  if (stats.isError) {
    return (
      <p className="text-sm" role="alert">
        {t("loadFailed")}
      </p>
    );
  }
  const data = stats.data;
  if (data.pairs === 0) return <p className="text-muted-foreground text-sm">{t("none")}</p>;
  const level = agreementLevel(data.overall);
  const number = (value: number | null) => (value === null ? "–" : value.toFixed(2));
  return (
    <div className="grid gap-2 text-sm">
      <p>
        <Badge tone={level === "strong" ? "success" : level === "weak" ? "warning" : "neutral"}>
          {t(`levels.${level}`)}
        </Badge>{" "}
        {t("counts", { pairs: data.pairs, reviewers: data.reviewers, questions: data.questions })}
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-5">
        {(
          [
            ["kappa", number(data.overall.weighted_kappa)],
            ["spearman", number(data.overall.spearman)],
            ["gap", number(data.overall.mean_abs_diff)],
            [
              "withinOne",
              data.overall.within_one === null
                ? "–"
                : `${Math.round(data.overall.within_one * 100)}%`,
            ],
            [
              "bias",
              data.bias === null ? "–" : `${data.bias > 0 ? "+" : ""}${data.bias.toFixed(2)}`,
            ],
          ] as const
        ).map(([key, value]) => (
          <div key={key}>
            <dt className="text-muted-foreground text-xs">{t(key)}</dt>
            <dd className="tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** The interview's evaluation (PRD §44, §70, §79): the overall and skill scores with verified
 * quotes, strengths and gaps, then each question with the reviewer's own scores first and the
 * AI's beside them once saved (calibration). Admins can repeat the evaluation with its pinned
 * versions; with analytics access the organisation's agreement is shown. */
export function EvaluationCard({
  id,
  canRerun,
  canMeasure,
}: {
  id: string;
  canRerun: boolean;
  canMeasure: boolean;
}) {
  const t = useTranslations("interviews.evaluation");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const evaluation = useQuery({
    queryKey: evaluationKeys.detail(id),
    queryFn: () => getEvaluation(id),
    // Just after an interview ends there is no evaluation yet ("none"); it appears within moments.
    refetchInterval: (query) =>
      query.state.data?.state === "evaluating" || query.state.data?.state === "none"
        ? POLL_MS
        : false,
  });
  const [queued, setQueued] = useState(false);
  const [waived, setWaived] = useState(false);
  const mine = useQuery({ queryKey: evaluationKeys.mine(id), queryFn: () => listMyScores(id) });
  const rerun = useMutation({
    mutationFn: () => queueRerun(id),
    onSuccess: (result) => {
      setQueued(true);
      toast.success(t(result.action === "rerun" ? "rerunQueued" : "retryQueued"), {});
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.detail(id) });
    },
    onError: problems.show,
  });

  if (evaluation.isPending) return <Skeleton className="h-48 w-full lg:col-span-2" />;
  if (evaluation.isError || !evaluation.data) {
    return (
      <Card className="lg:col-span-2">
        <CardContent className="grid justify-items-start gap-2 pt-6">
          <p className="text-sm" role="alert">
            {t("loadFailed")}
          </p>
          <Button size="sm" variant="secondary" onClick={() => void evaluation.refetch()}>
            {t("retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }
  const { state, evaluation: body } = evaluation.data;
  const savedBy = new Map(
    (mine.data ?? []).map((row) => [
      row.question_id,
      { dimensions: row.dimensions as Record<string, number>, note: row.note },
    ]),
  );
  const canAct = canRerun && (state === "ready" || state === "failed" || state === "none");
  const progress = {
    saved: body ? body.questions.filter((q) => savedBy.has(q.question_id)).length : 0,
    total: body ? body.questions.length : 0,
  };
  const revealed = mine.isSuccess && summaryRevealed(progress, waived);

  return (
    <>
      <Card className="lg:col-span-2">
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle>{t("title")}</CardTitle>
          {canAct ? (
            <Button
              size="sm"
              variant="secondary"
              disabled={rerun.isPending || queued}
              onClick={() => rerun.mutate()}
            >
              {state === "ready" ? t("rerun") : t("retryEvaluation")}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          {state === "ready" && body && revealed ? (
            <Summary evaluation={body} />
          ) : state === "ready" && body ? (
            <div className="grid justify-items-start gap-2">
              <p className="text-muted-foreground text-sm">
                {mine.isError
                  ? t("loadFailed")
                  : t("hiddenUntilScored", { saved: progress.saved, total: progress.total })}
              </p>
              {mine.isSuccess ? (
                <Button size="sm" variant="secondary" onClick={() => setWaived(true)}>
                  {t("showWithoutScoring")}
                </Button>
              ) : null}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">{t(`states.${state}`)}</p>
          )}
        </CardContent>
      </Card>
      {state === "ready" && body && mine.isSuccess ? (
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("questions")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2">
            {/* Mounted once the reviewer's saved scores are known, so the form starts from them. */}
            {body.questions.map((question) => (
              <QuestionPanel
                key={question.question_id}
                interviewId={id}
                question={question}
                saved={savedBy.get(question.question_id)}
              />
            ))}
          </CardContent>
        </Card>
      ) : null}
      {canMeasure ? (
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("agreement.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <Agreement />
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}
