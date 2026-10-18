"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  Input,
  Label,
  NativeSelect,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { useEvaluationGate } from "@/interviews/use-evaluation-gate";
import { changeScore, getScores, reviewKeys, type ScoreValue } from "./api";

/** The evaluation's scores with the people's changes laid over the AI's (PRD §97 "score
 * modified"). The AI's score stays on record: a change shows beside it, with who made it and
 * why. */
export function ScoresPanel({ id, canModify }: { id: string; canModify: boolean }) {
  const t = useTranslations("review.scores");
  const format = useFormatter();
  const [asking, setAsking] = useState(false);
  const scores = useQuery({ queryKey: reviewKeys.scores(id), queryFn: () => getScores(id) });
  const gate = useEvaluationGate(id);
  if (scores.isPending || !gate.loaded) return <Skeleton className="h-32 w-full" />;
  if (scores.isError || !scores.data) {
    const notYet = isApiProblem(scores.error) && scores.error.code === "not-evaluated";
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">
            {notYet ? t("notEvaluated") : t("loadFailed")}
          </p>
        </CardContent>
      </Card>
    );
  }
  if (!gate.revealed) {
    // The AI's numbers wait, as on the evaluation card, so they don't set the reviewer's own.
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">
            {gate.failed
              ? t("loadFailed")
              : t("hiddenUntilScored", { saved: gate.progress.saved, total: gate.progress.total })}
          </p>
        </CardContent>
      </Card>
    );
  }
  const data = scores.data;
  const number = (value: number | null) =>
    value === null ? "—" : format.number(value, { maximumFractionDigits: 1 });
  const rows: { key: string; label: string; value: ScoreValue }[] = [
    { key: "overall", label: t("overall"), value: data.overall },
    { key: "communication", label: t("communication"), value: data.communication },
    ...Object.entries(data.skills).map(([skill, value]) => ({
      key: `skill:${skill}`,
      label: skill,
      value,
    })),
  ];
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("title")}</CardTitle>
        {canModify ? (
          <Button size="sm" variant="secondary" onClick={() => setAsking(true)}>
            {t("change")}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{t("caption")}</caption>
            <thead>
              <tr>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("what")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("ai")}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t("now")}
                </th>
                <th scope="col" className="py-1 font-medium">
                  {t("why")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-border border-t align-top">
                  <th scope="row" className="py-1 pr-3 font-normal">
                    {row.label}
                  </th>
                  <td className="py-1 pr-3 tabular-nums">{number(row.value.ai)}</td>
                  <td className="py-1 pr-3 font-medium tabular-nums">{number(row.value.value)}</td>
                  <td className="py-1 text-muted-foreground text-xs">
                    {row.value.change
                      ? t("changedBy", {
                          name: row.value.change.changed_by_name,
                          reason: row.value.change.reason,
                        })
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.changes.length > 0 ? (
          <details>
            <summary className="cursor-pointer text-sm">
              {t("history", { count: data.changes.length })}
            </summary>
            <ol className="mt-2 grid gap-1 text-xs">
              {data.changes.map((change) => (
                <li key={change.id}>
                  {t("historyLine", {
                    when: format.dateTime(new Date(change.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }),
                    name: change.changed_by_name,
                    what:
                      change.target ?? t(change.scope === "overall" ? "overall" : "communication"),
                    from: number(change.previous_score),
                    to: number(change.new_score),
                    reason: change.reason,
                  })}
                </li>
              ))}
            </ol>
          </details>
        ) : null}
        <p className="text-muted-foreground text-xs">{t("note")}</p>
      </CardContent>
      {asking ? (
        <ChangeDialog id={id} skills={Object.keys(data.skills)} onClose={() => setAsking(false)} />
      ) : null}
    </Card>
  );
}

function ChangeDialog({
  id,
  skills,
  onClose,
}: {
  id: string;
  skills: string[];
  onClose: () => void;
}) {
  const t = useTranslations("review.scores");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const field = useId();
  const options = [
    { value: "overall", label: t("overall") },
    { value: "communication", label: t("communication") },
    ...skills.map((skill) => ({ value: `skill:${skill}`, label: skill })),
  ];
  const [what, setWhat] = useState(options[0]?.value ?? "overall");
  const [score, setScore] = useState("");
  const [reason, setReason] = useState("");
  const parsed = Number(score);
  const valid = score.trim() !== "" && Number.isFinite(parsed) && parsed >= 0 && parsed <= 10;
  const save = useMutation({
    mutationFn: () =>
      changeScore(id, {
        scope: what.startsWith("skill:") ? "skill" : (what as "overall" | "communication"),
        target: what.startsWith("skill:") ? what.slice("skill:".length) : null,
        new_score: parsed,
        reason: reason.trim(),
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(reviewKeys.scores(id), next);
      toast.success(t("saved"), {});
      onClose();
    },
    onError: problems.show,
  });
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent title={t("changeTitle")} description={t("changeHint")} closeLabel={t("close")}>
        <form
          noValidate
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid && reason.trim()) save.mutate();
          }}
        >
          <Label htmlFor={`${field}-what`}>{t("what")}</Label>
          <NativeSelect
            id={`${field}-what`}
            value={what}
            onChange={(e) => setWhat(e.target.value)}
            options={options}
          />
          <Label htmlFor={`${field}-score`}>{t("newScore")}</Label>
          <Input
            id={`${field}-score`}
            type="number"
            inputMode="decimal"
            min={0}
            max={10}
            step={0.1}
            value={score}
            onChange={(e) => setScore(e.target.value)}
          />
          <Label htmlFor={`${field}-reason`}>{t("reason")}</Label>
          <Textarea
            id={`${field}-reason`}
            rows={3}
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {t("close")}
            </Button>
            <Button type="submit" disabled={save.isPending || !valid || reason.trim() === ""}>
              {t("save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
