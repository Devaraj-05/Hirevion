"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  Label,
  Sheet,
  SheetContent,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { useStepUp } from "@/admin/step-up";
import { FlagBadges } from "@/candidates/flags";
import { Pager } from "@/data/pager";
import { useCursorPage } from "@/data/use-cursor-page";
import {
  type Action,
  actOnApplications,
  exportRanking,
  getApplicationScreening,
  getScreeningSummary,
  listScreeningResults,
  type RankedApplication,
  screenJob,
} from "./api";
import { FACTORS } from "./settings-form";

const POLL_MS = 2_000;
const PAGE_SIZE = 50;
const STAGE_ACTIONS = ["shortlist", "hold", "review", "reject"] as const;

export const keys = {
  summary: (jobId: string) => ["jobs", "detail", jobId, "screening-summary"] as const,
  results: (jobId: string) => ["jobs", "detail", jobId, "screening-results"] as const,
  application: (id: string) => ["applications", id, "screening"] as const,
};

/** A score from a result's JSON, or a dash. */
const shown = (value: unknown): string | number => (typeof value === "number" ? value : "—");

function download(blob: Blob, name: string) {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

/** A job's Ranking tab (PRD §16, §18): screen, read the ranked candidates with their evidence,
 * and act on them one at a time or in bulk. */
export function RankingPanel({
  jobId,
  jobReference,
  canManage,
  pollMs = POLL_MS,
}: {
  jobId: string;
  jobReference: string;
  canManage: boolean;
  pollMs?: number;
}) {
  const t = useTranslations("screening");
  const stages = useTranslations("candidates.stages");
  const problems = useAdminProblem();
  const withStepUp = useStepUp();
  const queryClient = useQueryClient();
  const [running, setRunning] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<RankedApplication | null>(null);
  const [asking, setAsking] = useState<{ action: Action; ids: string[] } | null>(null);

  const summary = useQuery({
    queryKey: keys.summary(jobId),
    queryFn: () => getScreeningSummary(jobId),
    refetchInterval: (query) => (running && (query.state.data?.waiting ?? 1) > 0 ? pollMs : false),
  });
  const waiting = summary.data?.waiting;
  useEffect(() => {
    if (running && waiting === 0) {
      setRunning(false);
      void queryClient.invalidateQueries({ queryKey: keys.results(jobId) });
    }
  }, [running, waiting, queryClient, jobId]);
  const page = useCursorPage([...keys.results(jobId), running], (cursor) =>
    listScreeningResults(jobId, { cursor, limit: PAGE_SIZE }),
  );

  const screen = useMutation({
    mutationFn: () => screenJob(jobId),
    onSuccess: (queued) => {
      toast.success(t("ranking.queued", { count: queued }), {});
      setRunning(true);
      void queryClient.invalidateQueries({ queryKey: keys.summary(jobId) });
    },
    onError: problems.show,
  });

  const act = useMutation({
    mutationFn: (input: { action: Action; ids: string[]; reason?: string }) =>
      actOnApplications(jobId, {
        application_ids: input.ids,
        action: input.action,
        ...(input.reason ? { reason: input.reason } : {}),
      }),
    onSuccess: (changed) => {
      toast.success(t("actions.done", { count: changed.length }), {});
      setSelected(new Set());
      setAsking(null);
      void queryClient.invalidateQueries({ queryKey: keys.results(jobId) });
      void queryClient.invalidateQueries({ queryKey: keys.summary(jobId) });
    },
    onError: (error, input) => {
      if (isApiProblem(error) && error.code === "reason-required" && !input.reason) {
        setAsking({ action: input.action, ids: input.ids });
      } else problems.show(error);
    },
  });

  function run(action: Action, ids: string[]) {
    if (action === "reject") setAsking({ action, ids });
    else act.mutate({ action, ids });
  }

  async function exportAs(format: "csv" | "xlsx") {
    try {
      const file = await withStepUp(() => exportRanking(jobId, format));
      download(file, `${jobReference}-ranking.${format}`);
    } catch (error) {
      problems.show(error);
    }
  }

  const rows = page.rows;
  const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.application_id));
  const toggle = (id: string) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="grid gap-0.5 text-sm" aria-live="polite">
          {summary.data ? (
            <>
              <span>
                {t("ranking.progress", {
                  screened: summary.data.screened,
                  total: summary.data.applications,
                })}
              </span>
              {summary.data.waiting > 0 ? (
                <span className="text-muted-foreground">
                  {t("ranking.waiting", { count: summary.data.waiting })}
                </span>
              ) : null}
            </>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => void exportAs("csv")}>
            {t("ranking.exportCsv")}
          </Button>
          <Button variant="secondary" onClick={() => void exportAs("xlsx")}>
            {t("ranking.exportXlsx")}
          </Button>
          {canManage ? (
            <Button disabled={screen.isPending || running} onClick={() => screen.mutate()}>
              {summary.data?.screened ? t("ranking.screenAgain") : t("ranking.screen")}
            </Button>
          ) : null}
        </div>
      </div>

      {canManage && selected.size > 0 ? (
        <section
          aria-label={t("ranking.selected", { count: selected.size })}
          className="flex flex-wrap items-center gap-2 rounded-md bg-surface-muted p-2"
        >
          <span className="px-2 text-sm">{t("ranking.selected", { count: selected.size })}</span>
          {STAGE_ACTIONS.map((action) => (
            <Button
              key={action}
              size="sm"
              variant={action === "shortlist" ? "primary" : "secondary"}
              disabled={act.isPending}
              onClick={() => run(action, [...selected])}
            >
              {t(`actions.${action}`)}
            </Button>
          ))}
        </section>
      ) : null}

      {page.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("ranking.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("ranking.caption")}</caption>
            <thead className="bg-surface-muted">
              <tr>
                {canManage ? (
                  <th scope="col" className="w-8 px-3 py-2">
                    <Checkbox
                      aria-label={t("ranking.selectAll")}
                      checked={allSelected}
                      onCheckedChange={(checked) =>
                        setSelected(
                          checked === true
                            ? new Set(rows.map((row) => row.application_id))
                            : new Set(),
                        )
                      }
                    />
                  </th>
                ) : null}
                {(["rank", "candidate", "score", "skills", "experience", "stage"] as const).map(
                  (column) => (
                    <th key={column} scope="col" className="px-3 py-2 text-left font-medium">
                      {t(`ranking.${column}`)}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.application_id} className="border-border border-t align-top">
                  {canManage ? (
                    <td className="px-3 py-2">
                      <Checkbox
                        aria-label={t("ranking.select", { name: row.candidate.name })}
                        checked={selected.has(row.application_id)}
                        onCheckedChange={() => toggle(row.application_id)}
                      />
                    </td>
                  ) : null}
                  <td className="px-3 py-2 font-medium">{row.rank ?? "—"}</td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setOpen(row)}
                      aria-label={t("ranking.open", { name: row.candidate.name })}
                      className="grid text-left hover:underline focus-visible:underline"
                    >
                      <span className="font-medium">{row.candidate.name}</span>
                      {row.candidate.headline ? (
                        <span className="text-muted-foreground text-xs">
                          {row.candidate.headline}
                        </span>
                      ) : null}
                    </button>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {row.knockouts.length > 0 ? (
                        <Badge tone="warning">{t("ranking.knockout")}</Badge>
                      ) : null}
                      <FlagBadges flags={row.candidate.flags} />
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={(row.score ?? 0) >= 75 ? "success" : "neutral"}>
                      {row.score ?? "—"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">{shown(row.skill_match.required_score)}</td>
                  <td className="px-3 py-2">{shown(row.experience.score)}</td>
                  <td className="px-3 py-2">
                    <Badge>{stages(row.stage)}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager
        hasPrevious={page.hasPrevious}
        hasNext={page.hasNext}
        onPrevious={page.previousPage}
        onNext={page.nextPage}
      />

      {open ? (
        <EvidenceSheet
          application={open}
          canManage={canManage}
          onAction={(action) => run(action, [open.application_id])}
          onClose={() => setOpen(null)}
        />
      ) : null}
      {asking ? (
        <ReasonDialog
          action={asking.action}
          busy={act.isPending}
          onCancel={() => setAsking(null)}
          onConfirm={(reason) => act.mutate({ ...asking, reason })}
        />
      ) : null}
    </div>
  );
}

function ReasonDialog({
  action,
  busy,
  onCancel,
  onConfirm,
}: {
  action: Action;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const t = useTranslations("screening.actions");
  const id = useId();
  const [reason, setReason] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    if (reason.trim()) onConfirm(reason.trim());
  }
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onCancel())}>
      <DialogContent title={`${t(action)}: ${t("reasonTitle")}`} closeLabel={t("cancel")}>
        <form noValidate onSubmit={submit} className="grid gap-3">
          <p className="text-muted-foreground text-sm">{t("reasonHint")}</p>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-reason`}>{t("reason")}</Label>
            <Textarea
              id={`${id}-reason`}
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onCancel}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={busy || !reason.trim()}>
              {t("confirm")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EvidenceSheet({
  application,
  canManage,
  onAction,
  onClose,
}: {
  application: RankedApplication;
  canManage: boolean;
  onAction: (action: Action) => void;
  onClose: () => void;
}) {
  const t = useTranslations("screening");
  const stages = useTranslations("candidates.stages");
  const detail = useQuery({
    queryKey: keys.application(application.application_id),
    queryFn: () => getApplicationScreening(application.application_id),
  });
  const name = application.candidate.name;
  const result = detail.data?.result;
  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent
        className="w-[min(36rem,100vw)]"
        title={
          application.rank
            ? t("evidence.title", { name, rank: application.rank })
            : t("evidence.titleUnranked", { name })
        }
        closeLabel={t("evidence.close")}
        footer={
          canManage ? (
            <div className="flex flex-wrap justify-end gap-2">
              {STAGE_ACTIONS.map((action) => (
                <Button
                  key={action}
                  size="sm"
                  variant={action === "shortlist" ? "primary" : "secondary"}
                  onClick={() => onAction(action)}
                >
                  {t(`actions.${action}`)}
                </Button>
              ))}
            </div>
          ) : undefined
        }
      >
        {detail.isPending ? (
          <Skeleton className="h-64 w-full" />
        ) : !result ? (
          <p className="text-sm">{t("evidence.noResult")}</p>
        ) : (
          <div className="grid gap-4 text-sm">
            <ul className="grid gap-3">
              {FACTORS.map((factor) => {
                const item = result.factors[factor] as
                  | {
                      score: number;
                      evidence?: string[];
                      supported?: boolean;
                      matched?: string[];
                      missing?: string[];
                    }
                  | undefined;
                if (!item) return null;
                return (
                  <li key={factor} className="grid gap-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">
                        {t("evidence.factor", { name: t(`factors.${factor}`), score: item.score })}
                      </span>
                    </div>
                    <meter
                      min={0}
                      max={100}
                      value={item.score}
                      aria-label={t(`factors.${factor}`)}
                      className="h-2 w-full"
                    />
                    {item.supported === false ? (
                      <span className="text-warning text-xs">{t("evidence.unsupported")}</span>
                    ) : null}
                    {item.matched && item.matched.length > 0 ? (
                      <span className="text-xs">
                        {t("evidence.matched", { skills: item.matched.join(", ") })}
                      </span>
                    ) : null}
                    {item.missing && item.missing.length > 0 ? (
                      <span className="text-danger text-xs">
                        {t("evidence.missing", { skills: item.missing.join(", ") })}
                      </span>
                    ) : null}
                    {(item.evidence ?? []).map((quote) => (
                      <span key={quote} className="text-muted-foreground text-xs">
                        {t("evidence.quote", { quote })}
                      </span>
                    ))}
                  </li>
                );
              })}
            </ul>
            {(
              [
                ["strengths", result.strengths],
                ["concerns", result.concerns],
                ["missingRequirements", result.missing],
                ["knockouts", result.knockouts],
              ] as const
            ).map(([title, items]) =>
              items.length > 0 ? (
                <section key={title} className="grid gap-1">
                  <h3 className="font-medium">{t(`evidence.${title}`)}</h3>
                  <ul className="list-disc pl-5">
                    {items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </section>
              ) : null,
            )}
            {detail.data && detail.data.history.length > 0 ? (
              <section className="grid gap-1">
                <h3 className="font-medium">{t("evidence.history")}</h3>
                <ul className="grid gap-1 text-xs">
                  {detail.data.history.map((entry) => (
                    <li key={`${entry.created_at}-${entry.action}`}>
                      {t("evidence.historyEntry", {
                        action: entry.action,
                        from: entry.from_stage
                          ? stages(entry.from_stage as RankedApplication["stage"])
                          : "—",
                        to: entry.to_stage
                          ? stages(entry.to_stage as RankedApplication["stage"])
                          : "—",
                      })}
                      {entry.override ? ` (${t("evidence.override")})` : null}
                      {entry.reason ? ` — ${entry.reason}` : null}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            <p className="text-muted-foreground text-xs">
              {t("evidence.model", { model: result.model, prompt: result.prompt_version })}
            </p>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
