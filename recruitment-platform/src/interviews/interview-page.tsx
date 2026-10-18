"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Checkbox,
  Dialog,
  DialogContent,
  EmptyState,
  Input,
  Label,
  Skeleton,
  Textarea,
  toast,
} from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, SearchX } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useId, useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { getJobChoices } from "@/jobs/api";
import { PageHeader } from "@/page/page-header";
import { AccommodationsCard } from "./accommodations-card";
import {
  cancelInterview,
  getInterview,
  type Interview,
  interviewActions,
  interviewKeys,
  isoToLocal,
  localToIso,
  rescheduleInterview,
  STATUS_TONES,
  sendInvitation,
  setInterviewReviewers,
} from "./assigned-api";
import { EvaluationCard } from "./evaluation-card";
import { MonitoringPanel } from "./monitoring-panel";
import { TranscriptCard } from "./transcript-card";

type Asking = "reschedule" | "cancel" | "reviewers" | null;

// Interviews that have something to show of what happened in them.
const HAPPENED = new Set([
  "in_progress",
  "interrupted",
  "completed",
  "evaluating",
  "evaluated",
  "abandoned",
]);

// Interviews that ended and are evaluated, or about to be.
const EVALUATED = new Set(["completed", "evaluating", "evaluated"]);

/** One interview (PRD §24): its pinned template and policy, its window and status, who reviews
 * it, its history and the emails sent; and, for `canManage`, sending, rescheduling, cancelling
 * and choosing reviewers; with `canReview`, its evaluation and the reviewer's own scores (with
 * `canRerun` the admin's re-run, with `canMeasure` the organisation's agreement with the AI);
 * with `canMonitor`, the live monitoring of proctoring (and with `canReviewEvents` the review of
 * its events). The API checks every permission again. */
export function InterviewPage({
  id,
  canManage,
  canReview = false,
  canRerun = false,
  canMeasure = false,
  canMonitor = false,
  canReviewEvents = false,
}: {
  id: string;
  canManage: boolean;
  canReview?: boolean;
  canRerun?: boolean;
  canMeasure?: boolean;
  canMonitor?: boolean;
  canReviewEvents?: boolean;
}) {
  const t = useTranslations("interviews.assigned");
  const statuses = useTranslations("interviews.assigned.statuses");
  const format = useFormatter();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState<Asking>(null);
  const interview = useQuery({
    queryKey: interviewKeys.detail(id),
    queryFn: () => getInterview(id),
  });

  function saved(next: Interview, message: string) {
    queryClient.setQueryData(interviewKeys.detail(id), next);
    void queryClient.invalidateQueries({ queryKey: interviewKeys.list });
    setAsking(null);
    toast.success(message, {});
  }

  const invite = useMutation({
    mutationFn: () => sendInvitation(id),
    onSuccess: (next) => saved(next, t("invitationSent")),
    onError: problems.show,
  });

  if (interview.isPending) return <Skeleton className="h-64 w-full" />;
  if (interview.isError || !interview.data) {
    const missing = isApiProblem(interview.error) && interview.error.status === 404;
    return (
      <EmptyState
        icon={<SearchX />}
        title={missing ? t("notFound") : t("loadFailed")}
        description={missing ? t("notFoundHint") : t("loadFailedHint")}
      />
    );
  }
  const data = interview.data;
  const actions = canManage
    ? interviewActions(data.status)
    : { invite: false, reschedule: false, cancel: false };
  const when = (value: string | null | undefined) =>
    value ? format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" }) : "—";
  const policy = data.policy as {
    proctoring_level?: string;
    checks?: string[];
    third_eye?: string;
    recording?: Record<string, boolean>;
  };

  return (
    <>
      <Link
        href="/interviews"
        className="mb-2 inline-flex items-center gap-1 text-muted-foreground text-sm hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t("back")}
      </Link>
      <PageHeader
        title={t("pageTitle", { reference: data.reference, name: data.candidate.name })}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Badge tone={STATUS_TONES[data.status]}>{statuses(data.status)}</Badge>
        {canReview && EVALUATED.has(data.status) ? (
          <Button asChild size="sm" variant="secondary">
            <Link href={`/interviews/${id}/review`}>{t("openReview")}</Link>
          </Button>
        ) : null}
        {actions.invite ? (
          <Button size="sm" disabled={invite.isPending} onClick={() => invite.mutate()}>
            {data.status === "scheduled" ? t("sendInvitation") : t("resendInvitation")}
          </Button>
        ) : null}
        {actions.reschedule ? (
          <Button size="sm" variant="secondary" onClick={() => setAsking("reschedule")}>
            {t("reschedule")}
          </Button>
        ) : null}
        {actions.cancel ? (
          <Button size="sm" variant="secondary" onClick={() => setAsking("cancel")}>
            {t("cancel")}
          </Button>
        ) : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("overview")}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">{t("candidate")}</dt>
              <dd>
                <Link href={`/candidates/${data.candidate.id}`} className="hover:underline">
                  {data.candidate.name}
                </Link>
                {data.candidate_email ? (
                  <span className="text-muted-foreground">
                    {t("emailAfterName", { email: data.candidate_email })}
                  </span>
                ) : null}
              </dd>
              <dt className="text-muted-foreground">{t("job")}</dt>
              <dd>
                <Link href={`/jobs/${data.job_id}`} className="hover:underline">
                  {data.job_title}
                </Link>
              </dd>
              <dt className="text-muted-foreground">{t("template")}</dt>
              <dd>
                <Link
                  href={`/interviews/templates/${data.template_id}`}
                  className="hover:underline"
                >
                  {t("templateVersion", {
                    name: data.template_name,
                    version: data.template_version,
                  })}
                </Link>
              </dd>
              <dt className="text-muted-foreground">{t("window")}</dt>
              <dd>
                {t("windowValue", {
                  start: when(data.starts_at),
                  end: when(data.expires_at),
                  zone: data.timezone,
                })}
              </dd>
              <dt className="text-muted-foreground">{t("duration")}</dt>
              <dd>{t("minutes", { minutes: data.duration_minutes })}</dd>
              {data.reschedule_count > 0 ? (
                <>
                  <dt className="text-muted-foreground">{t("rescheduled")}</dt>
                  <dd>{t("rescheduledCount", { count: data.reschedule_count })}</dd>
                </>
              ) : null}
              {data.cancel_reason ? (
                <>
                  <dt className="text-muted-foreground">{t("cancelReason")}</dt>
                  <dd>{data.cancel_reason}</dd>
                </>
              ) : null}
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("policy")}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">{t("proctoring")}</dt>
              <dd>
                {policy.proctoring_level}
                {policy.checks?.length ? ` (${policy.checks.join(", ")})` : ""}
              </dd>
              <dt className="text-muted-foreground">{t("thirdEye")}</dt>
              <dd>{policy.third_eye}</dd>
              <dt className="text-muted-foreground">{t("recording")}</dt>
              <dd>
                {Object.entries(policy.recording ?? {})
                  .filter(([, on]) => on)
                  .map(([what]) => what)
                  .join(", ") || "—"}
              </dd>
            </dl>
            <p className="mt-3 text-muted-foreground text-xs">{t("policyPinned")}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{t("reviewers")}</CardTitle>
            {canManage ? (
              <Button size="sm" variant="ghost" onClick={() => setAsking("reviewers")}>
                {t("editReviewers")}
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            {data.reviewers.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("noReviewers")}</p>
            ) : (
              <ul className="grid gap-1 text-sm">
                {data.reviewers.map((person) => (
                  <li key={person.id}>{person.name}</li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("emails")}</CardTitle>
          </CardHeader>
          <CardContent>
            {data.invitations.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("noEmails")}</p>
            ) : (
              <ul className="grid gap-1 text-sm">
                {data.invitations.map((item) => (
                  <li key={item.id}>
                    {t("emailLine", {
                      kind: t(`emailKinds.${item.kind}`),
                      to: item.sent_to,
                      when: when(item.created_at),
                    })}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <AccommodationsCard
          id={id}
          canDecide={canManage && (data.status === "scheduled" || data.status === "invited")}
        />
        {canMonitor && HAPPENED.has(data.status) ? (
          <MonitoringPanel
            id={id}
            live={data.status === "in_progress" || data.status === "interrupted"}
            canReview={canReviewEvents}
          />
        ) : null}
        {HAPPENED.has(data.status) ? (
          <TranscriptCard
            id={id}
            live={data.status === "in_progress" || data.status === "interrupted"}
          />
        ) : null}
        {canReview && EVALUATED.has(data.status) ? (
          <EvaluationCard id={id} canRerun={canRerun} canMeasure={canMeasure} />
        ) : null}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("history")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="grid gap-2 text-sm">
              {data.events.map((event) => (
                <li key={event.id} className="flex flex-wrap gap-x-2">
                  <span className="text-muted-foreground">{when(event.created_at)}</span>
                  <span className="font-medium">{statuses(event.to_status)}</span>
                  <span>{event.action}</span>
                  {event.reason ? (
                    <span className="text-muted-foreground">
                      {t("eventReason", { reason: event.reason })}
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>
      {asking === "reschedule" ? (
        <RescheduleDialog
          interview={data}
          onCancel={() => setAsking(null)}
          onSaved={(next) => saved(next, t("rescheduledToast"))}
        />
      ) : null}
      {asking === "cancel" ? (
        <CancelDialog
          interview={data}
          onCancel={() => setAsking(null)}
          onSaved={(next) => saved(next, t("cancelledToast"))}
        />
      ) : null}
      {asking === "reviewers" ? (
        <ReviewersDialog
          interview={data}
          onCancel={() => setAsking(null)}
          onSaved={(next) => saved(next, t("reviewersSaved"))}
        />
      ) : null}
    </>
  );
}

function RescheduleDialog({
  interview,
  onCancel,
  onSaved,
}: {
  interview: Interview;
  onCancel: () => void;
  onSaved: (interview: Interview) => void;
}) {
  const t = useTranslations("interviews.assigned");
  const problems = useAdminProblem();
  const id = useId();
  const [startsAt, setStartsAt] = useState(isoToLocal(interview.starts_at));
  const [expiresAt, setExpiresAt] = useState(isoToLocal(interview.expires_at));
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      rescheduleInterview(interview.id, {
        starts_at: localToIso(startsAt),
        expires_at: localToIso(expiresAt),
        reason: reason.trim() || null,
      }),
    onSuccess: onSaved,
    onError: problems.show,
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onCancel())}>
      <DialogContent title={t("rescheduleTitle")} closeLabel={t("close")}>
        <form noValidate onSubmit={submit} className="grid gap-3">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-starts`}>{t("startsAt")}</Label>
              <Input
                id={`${id}-starts`}
                type="datetime-local"
                value={startsAt}
                onChange={(event) => setStartsAt(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-expires`}>{t("expiresAt")}</Label>
              <Input
                id={`${id}-expires`}
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-reason`}>{t("reasonOptional")}</Label>
            <Textarea
              id={`${id}-reason`}
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onCancel}>
              {t("close")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {t("reschedule")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CancelDialog({
  interview,
  onCancel,
  onSaved,
}: {
  interview: Interview;
  onCancel: () => void;
  onSaved: (interview: Interview) => void;
}) {
  const t = useTranslations("interviews.assigned");
  const problems = useAdminProblem();
  const id = useId();
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => cancelInterview(interview.id, reason.trim()),
    onSuccess: onSaved,
    onError: problems.show,
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (reason.trim()) save.mutate();
  }
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onCancel())}>
      <DialogContent title={t("cancelTitle")} description={t("cancelHint")} closeLabel={t("close")}>
        <form noValidate onSubmit={submit} className="grid gap-3">
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
              {t("close")}
            </Button>
            <Button type="submit" variant="danger" disabled={save.isPending || !reason.trim()}>
              {t("cancel")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReviewersDialog({
  interview,
  onCancel,
  onSaved,
}: {
  interview: Interview;
  onCancel: () => void;
  onSaved: (interview: Interview) => void;
}) {
  const t = useTranslations("interviews.assigned");
  const problems = useAdminProblem();
  const people = useQuery({ queryKey: ["jobs", "choices"], queryFn: getJobChoices });
  const [chosen, setChosen] = useState(new Set(interview.reviewers.map((person) => person.id)));
  const save = useMutation({
    mutationFn: () => setInterviewReviewers(interview.id, [...chosen]),
    onSuccess: onSaved,
    onError: problems.show,
  });
  function toggle(personId: string) {
    setChosen((previous) => {
      const next = new Set(previous);
      if (next.has(personId)) next.delete(personId);
      else next.add(personId);
      return next;
    });
  }
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onCancel())}>
      <DialogContent title={t("reviewersTitle")} closeLabel={t("close")}>
        <div className="grid gap-3">
          <ul className="grid max-h-72 gap-2 overflow-y-auto text-sm">
            {(people.data?.people ?? []).map((person) => (
              <li key={person.id} className="flex items-center gap-2">
                <Checkbox
                  id={`reviewer-${person.id}`}
                  checked={chosen.has(person.id)}
                  onCheckedChange={() => toggle(person.id)}
                />
                <Label htmlFor={`reviewer-${person.id}`}>{person.name}</Label>
              </li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onCancel}>
              {t("close")}
            </Button>
            <Button disabled={save.isPending} onClick={() => save.mutate()}>
              {t("saveReviewers")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
