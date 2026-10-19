"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  Label,
  NativeSelect,
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
import { QueryFailed } from "@/data/query-failed";
import { useCursorPage } from "@/data/use-cursor-page";
import { AssignDialog } from "@/interviews/assign-dialog";
import { getJobChoices } from "@/jobs/api";
import {
  type Action,
  actOnApplications,
  exportRanking,
  type ApplicationScreening,
  getApplicationScreening,
  getScreeningSummary,
  listScreeningResults,
  type RankedApplication,
  screenJob,
} from "./api";
import { FACTORS } from "./settings-form";

const POLL_MS = 2_000;
const SETTLE_POLLS = 2;
const PAGE_SIZE = 50;
const STAGE_ACTIONS = ["shortlist", "hold", "review", "reject"] as const;
const ASSIGN_ACTIONS = ["assign_recruiter", "assign_hiring_manager"] as const;

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
  canCreateInterviews = false,
  interviewTemplateId = null,
  pollMs = POLL_MS,
}: {
  jobId: string;
  jobReference: string;
  canManage: boolean;
  /** `interviews.manage`: offers "Create interview" for the selected candidates (SP-07a). */
  canCreateInterviews?: boolean;
  interviewTemplateId?: string | null;
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
  const [startedAt, setStartedAt] = useState(0);
  const [asking, setAsking] = useState<{ action: Action; ids: string[] } | null>(null);
  const [assigning, setAssigning] = useState<string[] | null>(null);
  const [choosing, setChoosing] = useState<{
    action: (typeof ASSIGN_ACTIONS)[number];
    ids: string[];
  } | null>(null);

  const summary = useQuery({
    queryKey: keys.summary(jobId),
    queryFn: () => getScreeningSummary(jobId),
    refetchInterval: running ? pollMs : false,
  });
  const waiting = summary.data?.waiting;
  const updatedAt = summary.dataUpdatedAt;
  // Screening again changes no candidate's stage when their results are still current, so
  // "nobody is waiting" is true from the first moment: the run is over once it has had time to
  // work through the queue (and nobody waits), and the results are read again on every poll.
  useEffect(() => {
    if (!running) return;
    void queryClient.invalidateQueries({ queryKey: keys.results(jobId) });
    if (waiting === 0 && Date.now() - startedAt >= pollMs * SETTLE_POLLS) setRunning(false);
  }, [running, waiting, updatedAt, startedAt, pollMs, queryClient, jobId]);
  const page = useCursorPage(keys.results(jobId), (cursor) =>
    listScreeningResults(jobId, { cursor, limit: PAGE_SIZE }),
  );

  const screen = useMutation({
    mutationFn: () => screenJob(jobId),
    onSuccess: (queued) => {
      toast.success(t("ranking.queued", { count: queued }), {});
      setStartedAt(Date.now());
      setRunning(true);
      void queryClient.invalidateQueries({ queryKey: keys.summary(jobId) });
    },
    onError: problems.show,
  });

  const act = useMutation({
    mutationFn: (input: { action: Action; ids: string[]; reason?: string; userId?: string }) =>
      actOnApplications(jobId, {
        application_ids: input.ids,
        action: input.action,
        ...(input.reason ? { reason: input.reason } : {}),
        ...(input.userId !== undefined ? { user_id: input.userId || null } : {}),
      }),
    onSuccess: (changed) => {
      toast.success(t("actions.done", { count: changed.length }), {});
      setSelected(new Set());
      setAsking(null);
      setChoosing(null);
      void queryClient.invalidateQueries({ queryKey: keys.results(jobId) });
      void queryClient.invalidateQueries({ queryKey: keys.summary(jobId) });
      // Each candidate's own history changed too.
      void queryClient.invalidateQueries({ queryKey: ["applications"] });
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
  const shownBlind = rows.length > 0 && rows.every((row) => row.blind === true);
  const shownOpen = rows.some((row) => row.blind === false);
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
          {ASSIGN_ACTIONS.map((action) => (
            <Button
              key={action}
              size="sm"
              variant="secondary"
              disabled={act.isPending}
              onClick={() => setChoosing({ action, ids: [...selected] })}
            >
              {t(`actions.${action}`)}
            </Button>
          ))}
          {canCreateInterviews ? (
            <Button size="sm" variant="secondary" onClick={() => setAssigning([...selected])}>
              {t("ranking.createInterview")}
            </Button>
          ) : null}
        </section>
      ) : null}

      {shownBlind ? (
        <p className="text-muted-foreground text-xs">{t("ranking.blindNote")}</p>
      ) : null}
      {shownOpen ? (
        <p role="status" className="text-warning text-xs">
          {t("ranking.notBlind")}
        </p>
      ) : null}
      {page.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : page.error && rows.length === 0 ? (
        <QueryFailed onRetry={page.refetch} />
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
                      {row.blind === false ? (
                        <Badge tone="warning">{t("ranking.notBlindBadge")}</Badge>
                      ) : null}
                      <FlagBadges flags={row.candidate.flags} />
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={(row.score ?? 0) >= 75 ? "success" : "neutral"}>
                      {row.score ?? "—"}
                    </Badge>
                    {row.semantic_similarity != null ? (
                      <span className="mt-1 block text-muted-foreground text-xs">
                        {t("ranking.semantic", { value: row.semantic_similarity.toFixed(2) })}
                      </span>
                    ) : null}
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
      {assigning ? (
        <AssignDialog
          applicationIds={assigning}
          names={Object.fromEntries(rows.map((row) => [row.application_id, row.candidate.name]))}
          defaultTemplateId={interviewTemplateId}
          onCancel={() => setAssigning(null)}
          onDone={() => {
            setAssigning(null);
            setSelected(new Set());
            void queryClient.invalidateQueries({ queryKey: keys.results(jobId) });
          }}
        />
      ) : null}
      {choosing ? (
        <PersonDialog
          action={choosing.action}
          busy={act.isPending}
          onCancel={() => setChoosing(null)}
          onConfirm={(userId) => act.mutate({ action: choosing.action, ids: choosing.ids, userId })}
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

/** Who a bulk "assign recruiter" or "assign hiring manager" gives the candidates to. */
function PersonDialog({
  action,
  busy,
  onCancel,
  onConfirm,
}: {
  action: (typeof ASSIGN_ACTIONS)[number];
  busy: boolean;
  onCancel: () => void;
  onConfirm: (userId: string) => void;
}) {
  const t = useTranslations("screening");
  const id = useId();
  const [person, setPerson] = useState("");
  const choices = useQuery({ queryKey: ["jobs", "choices"], queryFn: getJobChoices });
  function submit(event: FormEvent) {
    event.preventDefault();
    onConfirm(person);
  }
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onCancel())}>
      <DialogContent title={t(`actions.${action}`)} closeLabel={t("actions.cancel")}>
        <form noValidate onSubmit={submit} className="grid gap-3">
          {choices.isError ? <QueryFailed onRetry={() => void choices.refetch()} /> : null}
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-person`}>{t("assign.person")}</Label>
            <NativeSelect
              id={`${id}-person`}
              value={person}
              onChange={(event) => setPerson(event.target.value)}
              options={[
                { value: "", label: t("assign.nobody") },
                ...(choices.data?.people ?? []).map((user) => ({
                  value: user.id,
                  label: user.name,
                })),
              ]}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onCancel}>
              {t("actions.cancel")}
            </Button>
            <Button type="submit" disabled={busy}>
              {t("assign.confirm")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
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

/** What happened to the candidate, in words: each stage change, who gave a reason, and whether
 * it went against the ranking. */
function History({ entries }: { entries: ApplicationScreening["history"] }) {
  const t = useTranslations("screening");
  const stages = useTranslations("candidates.stages");
  if (entries.length === 0) return null;
  const stage = (value: string | null) =>
    value ? stages(value as RankedApplication["stage"]) : "—";
  return (
    <section className="grid gap-1">
      <h3 className="font-medium">{t("evidence.history")}</h3>
      <ul className="grid gap-1 text-xs">
        {entries.map((entry) => (
          <li key={`${entry.created_at}-${entry.action}`}>
            {t("evidence.historyEntry", {
              action: t.has(`evidence.historyActions.${entry.action}`)
                ? t(`evidence.historyActions.${entry.action}`)
                : entry.action,
              from: stage(entry.from_stage),
              to: stage(entry.to_stage),
            })}
            {entry.override ? ` (${t("evidence.override")})` : null}
            {entry.reason ? ` — ${entry.reason}` : null}
          </li>
        ))}
      </ul>
    </section>
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
        ) : detail.isError ? (
          <QueryFailed onRetry={() => void detail.refetch()} />
        ) : !result ? (
          <div className="grid gap-4 text-sm">
            <p>{t("evidence.noResult")}</p>
            <History entries={detail.data?.history ?? []} />
          </div>
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
            <History entries={detail.data?.history ?? []} />
            {result.semantic_similarity != null ? (
              <p className="text-muted-foreground text-xs">
                {t("evidence.similarity", { value: result.semantic_similarity.toFixed(2) })}
              </p>
            ) : null}
            {result.blind != null ? (
              <p className="text-muted-foreground text-xs">
                {result.blind ? t("evidence.blind") : t("evidence.notBlind")}
              </p>
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
