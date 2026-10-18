"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
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
import {
  addHiringInput,
  changeHiringStatus,
  getHiringState,
  type HiringState,
  type HiringStatus,
  REASON_REQUIRED,
  RECOMMENDATIONS,
  type Recommendation,
  reviewKeys,
} from "./api";

const RATINGS = ["technical", "communication", "role_fit"] as const;
const DECISIONS: readonly HiringStatus[] = ["selected", "rejected"];

/** Where the hiring stands (PRD §72) and what people add to it: the status with its history, the
 * final decision (only for someone authorised to make it), and the Hiring Managers' recommendations
 * with their reasons, which never move the status by themselves. */
export function HiringPanel({
  applicationId,
  canInput,
  onChanged,
}: {
  applicationId: string;
  canInput: boolean;
  onChanged?: () => void;
}) {
  const t = useTranslations("hiring");
  const format = useFormatter();
  const [moving, setMoving] = useState(false);
  const state = useQuery({
    queryKey: reviewKeys.hiring(applicationId),
    queryFn: () => getHiringState(applicationId),
  });
  if (state.isPending) return <Skeleton className="h-40 w-full" />;
  if (state.isError || !state.data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">{t("loadFailed")}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  const when = (value: string) =>
    format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" });
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>{t("title")}</CardTitle>
        {data.allowed.length > 0 ? (
          <Button size="sm" variant="secondary" onClick={() => setMoving(true)}>
            {t("change")}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        <p>
          <span className="text-muted-foreground">{t("status")} </span>
          <Badge
            tone={
              data.status === "rejected"
                ? "danger"
                : data.status === "selected"
                  ? "success"
                  : "neutral"
            }
          >
            {t(`statuses.${data.status}`)}
          </Badge>
        </p>
        {data.decision ? (
          <p role="note" className="rounded-md border border-border bg-surface-muted px-3 py-2">
            {t("decided", {
              decision: t(`statuses.${data.decision.to_status}`),
              name: data.decision.actor_name ?? t("someone"),
              when: when(data.decision.created_at),
              reason: data.decision.reason ?? "",
            })}
          </p>
        ) : null}
        <section aria-labelledby={`${applicationId}-inputs`} className="grid gap-2">
          <h3 id={`${applicationId}-inputs`} className="font-medium">
            {t("inputs")}
          </h3>
          {data.inputs.length === 0 ? (
            <p className="text-muted-foreground">{t("noInputs")}</p>
          ) : (
            <ul className="grid gap-2">
              {data.inputs.map((item) => (
                <li key={item.id} className="grid gap-0.5 border-border border-t pt-2">
                  <span className="font-medium">
                    {t("inputLine", {
                      name: item.author_name,
                      recommendation: t(`recommendations.${item.recommendation}`),
                    })}
                  </span>
                  {Object.keys(item.ratings).length > 0 ? (
                    <span className="text-muted-foreground text-xs">
                      {Object.entries(item.ratings)
                        .map(([name, value]) =>
                          t("rating", { name: t(`ratings.${name as "technical"}`), value }),
                        )
                        .join(" · ")}
                    </span>
                  ) : null}
                  <span className="whitespace-pre-wrap break-words">{item.rationale}</span>
                </li>
              ))}
            </ul>
          )}
          {canInput ? <InputForm applicationId={applicationId} /> : null}
        </section>
        <details>
          <summary className="cursor-pointer">
            {t("history", { count: data.history.length })}
          </summary>
          <ol className="mt-2 grid gap-1 text-xs">
            {data.history.map((row) => (
              <li key={row.id}>
                {t("historyLine", {
                  when: when(row.created_at),
                  from: row.from_status ? t(`statuses.${row.from_status}`) : "—",
                  to: t(`statuses.${row.to_status}`),
                  who: row.actor_name ?? t(row.source === "system" ? "system" : "someone"),
                  reason: row.reason ?? "",
                })}
              </li>
            ))}
          </ol>
        </details>
      </CardContent>
      {moving ? (
        <MoveDialog
          applicationId={applicationId}
          state={data}
          onClose={() => setMoving(false)}
          onMoved={() => {
            setMoving(false);
            onChanged?.();
          }}
        />
      ) : null}
    </Card>
  );
}

function InputForm({ applicationId }: { applicationId: string }) {
  const t = useTranslations("hiring");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const field = useId();
  const [recommendation, setRecommendation] = useState<Recommendation>("hire");
  const [ratings, setRatings] = useState<Record<string, string>>({});
  const [rationale, setRationale] = useState("");
  const save = useMutation({
    mutationFn: () =>
      addHiringInput(applicationId, {
        recommendation,
        ratings: Object.fromEntries(
          Object.entries(ratings)
            .filter(([, value]) => value !== "")
            .map(([name, value]) => [name, Number(value)]),
        ),
        rationale: rationale.trim(),
      }),
    onSuccess: () => {
      setRationale("");
      toast.success(t("inputSaved"), {});
      void queryClient.invalidateQueries({ queryKey: reviewKeys.hiring(applicationId) });
    },
    onError: problems.show,
  });
  const scale = [
    { value: "", label: t("unrated") },
    ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) })),
  ];
  return (
    <form
      noValidate
      className="grid gap-2 rounded-md border border-border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (rationale.trim()) save.mutate();
      }}
    >
      <h4 className="font-medium">{t("giveInput")}</h4>
      <Label htmlFor={`${field}-rec`}>{t("recommendation")}</Label>
      <NativeSelect
        id={`${field}-rec`}
        value={recommendation}
        onChange={(e) => setRecommendation(e.target.value as Recommendation)}
        options={RECOMMENDATIONS.map((value) => ({ value, label: t(`recommendations.${value}`) }))}
      />
      <div className="grid gap-2 sm:grid-cols-3">
        {RATINGS.map((name) => (
          <div key={name} className="grid gap-1">
            <Label htmlFor={`${field}-${name}`}>{t(`ratings.${name}`)}</Label>
            <NativeSelect
              id={`${field}-${name}`}
              value={ratings[name] ?? ""}
              onChange={(e) => setRatings({ ...ratings, [name]: e.target.value })}
              options={scale}
            />
          </div>
        ))}
      </div>
      <Label htmlFor={`${field}-why`}>{t("rationale")}</Label>
      <Textarea
        id={`${field}-why`}
        rows={3}
        maxLength={4000}
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
      />
      <div>
        <Button type="submit" size="sm" disabled={save.isPending || rationale.trim() === ""}>
          {t("saveInput")}
        </Button>
      </div>
    </form>
  );
}

/** Moving an application to another status. A decision (selected, or a rejection after an
 * interview) says so, and every reason is kept with the change. */
export function MoveDialog({
  applicationId,
  state,
  initial,
  onClose,
  onMoved,
}: {
  applicationId: string;
  state: Pick<HiringState, "status" | "allowed" | "has_interview">;
  initial?: HiringStatus;
  onClose: () => void;
  onMoved: (next: HiringState) => void;
}) {
  const t = useTranslations("hiring");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const field = useId();
  const [target, setTarget] = useState<HiringStatus>(initial ?? state.allowed[0] ?? state.status);
  const [reason, setReason] = useState("");
  const needsReason = REASON_REQUIRED.includes(target);
  const decisive = DECISIONS.includes(target) && (target === "selected" || state.has_interview);
  const save = useMutation({
    mutationFn: () =>
      changeHiringStatus(applicationId, { status: target, reason: reason.trim() || null }),
    onSuccess: (next) => {
      queryClient.setQueryData(reviewKeys.hiring(applicationId), next);
      void queryClient.invalidateQueries({ queryKey: ["review", "pipeline"] });
      void queryClient.invalidateQueries({ queryKey: reviewKeys.pending });
      toast.success(t("moved", { status: t(`statuses.${next.status}`) }), {});
      onMoved(next);
    },
    onError: (error) => {
      if (isApiProblem(error) && error.code === "decision-forbidden")
        toast.error(t("notAllowed"), {});
      else problems.show(error);
    },
  });
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent title={t("moveTitle")} description={t("moveHint")} closeLabel={t("close")}>
        <form
          noValidate
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!needsReason || reason.trim()) save.mutate();
          }}
        >
          <Label htmlFor={`${field}-to`}>{t("moveTo")}</Label>
          <NativeSelect
            id={`${field}-to`}
            value={target}
            onChange={(e) => setTarget(e.target.value as HiringStatus)}
            options={state.allowed.map((value) => ({ value, label: t(`statuses.${value}`) }))}
          />
          <Label htmlFor={`${field}-reason`}>
            {needsReason ? t("reason") : t("reasonOptional")}
          </Label>
          <Textarea
            id={`${field}-reason`}
            rows={3}
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {decisive ? (
            <p
              role="note"
              className="rounded-md border border-border bg-surface-muted px-3 py-2 text-sm"
            >
              {t("decisionWarning")}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {t("close")}
            </Button>
            <Button
              type="submit"
              disabled={save.isPending || (needsReason && reason.trim() === "")}
            >
              {decisive ? t("decide") : t("move")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
