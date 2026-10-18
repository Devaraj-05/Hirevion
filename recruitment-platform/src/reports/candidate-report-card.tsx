"use client";

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
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import {
  approveCandidateReport,
  type CandidateReport,
  getCandidateReportState,
  reportKeys,
  saveCandidateReport,
  withdrawCandidateReport,
} from "./api";

/** What the candidate may see of their interview (PRD §99): the draft a recruiter edits, which
 * items the organisation allows at all, and the release. A release is frozen as it reads when
 * approved; withdrawing takes it off the candidate's page. */
export function CandidateReportCard({ id, canRelease }: { id: string; canRelease: boolean }) {
  const t = useTranslations("reports.candidateVisible");
  const state = useQuery({
    queryKey: reportKeys.candidateReport(id),
    queryFn: () => getCandidateReportState(id),
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
  return (
    <Editor
      // A release or a withdrawal starts the editor over from what the server holds.
      key={`${state.data.status}-${state.data.approved_at ?? ""}-${state.data.withdrawn_at ?? ""}`}
      id={id}
      data={state.data}
      canRelease={canRelease}
    />
  );
}

function Editor({
  id,
  data,
  canRelease,
}: {
  id: string;
  data: CandidateReport;
  canRelease: boolean;
}) {
  const t = useTranslations("reports.candidateVisible");
  const format = useFormatter();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const base = useId();
  const [drafts, setDrafts] = useState(
    Object.fromEntries(
      data.items.map((item) => [item.key, { text: item.text, include: item.include }]),
    ),
  );
  const [withdrawing, setWithdrawing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const released = data.status === "released";

  function saved(next: CandidateReport, message: string) {
    queryClient.setQueryData(reportKeys.candidateReport(id), next);
    toast.success(message, {});
    setWithdrawing(false);
    setConfirming(false);
  }
  const save = useMutation({
    mutationFn: () => saveCandidateReport(id, drafts),
    onSuccess: (next) => saved(next, t("saved")),
    onError: problems.show,
  });
  const approve = useMutation({
    mutationFn: async () => {
      await saveCandidateReport(id, drafts);
      return approveCandidateReport(id);
    },
    onSuccess: (next) => saved(next, t("released")),
    onError: problems.show,
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>{t("title")}</CardTitle>
        <Badge tone={released ? "success" : data.status === "withdrawn" ? "warning" : "neutral"}>
          {t(`status.${data.status}`)}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="text-muted-foreground text-sm">{t("intro")}</p>
        {!data.ready ? (
          <p className="text-muted-foreground text-sm">{t("notReady")}</p>
        ) : released ? (
          <>
            <p className="text-sm">
              {t("releasedBy", {
                name: data.approved_by_name ?? t("someone"),
                when: data.approved_at
                  ? format.dateTime(new Date(data.approved_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })
                  : "",
              })}
            </p>
            <ul className="grid gap-2 text-sm">
              {data.released.map((item) => (
                <li key={item.key} className="grid gap-0.5 border-border border-t pt-2">
                  <span className="font-medium">{item.title}</span>
                  <span className="whitespace-pre-wrap break-words">{item.text}</span>
                </li>
              ))}
            </ul>
            {canRelease ? (
              <div>
                <Button variant="secondary" size="sm" onClick={() => setWithdrawing(true)}>
                  {t("withdraw")}
                </Button>
              </div>
            ) : null}
          </>
        ) : (
          <>
            {data.status === "withdrawn" ? (
              <p
                role="note"
                className="rounded-md border border-border bg-surface-muted px-3 py-2 text-sm"
              >
                {t("withdrawn", { reason: data.withdrawn_reason ?? "" })}
              </p>
            ) : null}
            {data.items.map((item) => {
              const draft = drafts[item.key] ?? { text: "", include: false };
              return (
                <fieldset
                  key={item.key}
                  className="grid gap-2 border-border border-t pt-3"
                  disabled={!canRelease}
                >
                  <legend className="font-medium text-sm">{item.title}</legend>
                  {item.allowed ? null : (
                    <p className="text-muted-foreground text-xs">{t("notAllowed")}</p>
                  )}
                  <Label htmlFor={`${base}-${item.key}`} className="sr-only">
                    {t("text", { item: item.title })}
                  </Label>
                  <Textarea
                    id={`${base}-${item.key}`}
                    rows={2}
                    maxLength={4000}
                    value={draft.text}
                    onChange={(e) =>
                      setDrafts({ ...drafts, [item.key]: { ...draft, text: e.target.value } })
                    }
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={draft.include}
                      disabled={!item.allowed}
                      onChange={(e) =>
                        setDrafts({
                          ...drafts,
                          [item.key]: { ...draft, include: e.target.checked },
                        })
                      }
                    />
                    {t("include")}
                  </label>
                </fieldset>
              );
            })}
            {canRelease ? (
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={save.isPending}
                  onClick={() => save.mutate()}
                >
                  {t("save")}
                </Button>
                <Button size="sm" disabled={approve.isPending} onClick={() => setConfirming(true)}>
                  {t("approve")}
                </Button>
              </div>
            ) : (
              <p className="text-muted-foreground text-xs">{t("readOnly")}</p>
            )}
          </>
        )}
      </CardContent>
      {confirming ? (
        <Dialog open onOpenChange={(open) => (open ? undefined : setConfirming(false))}>
          <DialogContent
            title={t("confirmTitle")}
            description={t("confirmHint")}
            closeLabel={t("close")}
          >
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                {t("close")}
              </Button>
              <Button disabled={approve.isPending} onClick={() => approve.mutate()}>
                {t("confirm")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
      {withdrawing ? (
        <WithdrawDialog
          id={id}
          onClose={() => setWithdrawing(false)}
          onDone={(next) => saved(next, t("withdrawnToast"))}
        />
      ) : null}
    </Card>
  );
}

function WithdrawDialog({
  id,
  onClose,
  onDone,
}: {
  id: string;
  onClose: () => void;
  onDone: (next: CandidateReport) => void;
}) {
  const t = useTranslations("reports.candidateVisible");
  const problems = useAdminProblem();
  const field = useId();
  const [reason, setReason] = useState("");
  const withdraw = useMutation({
    mutationFn: () => withdrawCandidateReport(id, reason.trim()),
    onSuccess: onDone,
    onError: problems.show,
  });
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={t("withdrawTitle")}
        description={t("withdrawHint")}
        closeLabel={t("close")}
      >
        <form
          noValidate
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (reason.trim()) withdraw.mutate();
          }}
        >
          <Label htmlFor={field}>{t("reason")}</Label>
          <Textarea
            id={field}
            rows={3}
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {t("close")}
            </Button>
            <Button
              type="submit"
              variant="danger"
              disabled={withdraw.isPending || reason.trim() === ""}
            >
              {t("withdraw")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
