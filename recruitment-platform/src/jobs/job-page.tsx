"use client";

import { isApiProblem } from "@hirevion/api-client";
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@hirevion/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, SearchX } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { type JobStatus, setJobStatus } from "./api";
import { DescriptionPanel } from "./description-panel";
import { HistoryPanel } from "./history-panel";
import { JobForm } from "./job-form";
import { keys, useJob } from "./queries";
import { STATUS_TONES, statusActions } from "./status";

/** One job (PRD §11–12): its status and the moves from it, then its details, its description
 * and its versions. `canEdit` is the reader's `jobs.create`; the API checks it again. */
export function JobPage({ id, canEdit }: { id: string; canEdit: boolean }) {
  const t = useTranslations("jobs");
  const titles = useTranslations("routes");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const job = useJob(id);
  const [incomplete, setIncomplete] = useState(false);

  const move = useMutation({
    mutationFn: (status: JobStatus) => setJobStatus(id, status),
    onMutate: () => setIncomplete(false),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.job(id), saved);
      void queryClient.invalidateQueries({ queryKey: keys.list });
      toast.success(t("statusChanged", { status: t(`statuses.${saved.status}`) }), {});
    },
    onError: (error) => {
      if (isApiProblem(error) && error.code === "job-incomplete") setIncomplete(true);
      else problems.show(error);
    },
  });

  // The job's title is the page's h1; until it's known, the page's own name is.
  const placeholderTitle = <h1 className="sr-only">{titles("jobsDetail")}</h1>;
  if (job.isPending) {
    return (
      <>
        {placeholderTitle}
        <Skeleton className="h-64 w-full" />
      </>
    );
  }
  if (job.isError) {
    const missing = isApiProblem(job.error) && job.error.status === 404;
    return (
      <>
        {placeholderTitle}
        <EmptyState
          icon={<SearchX />}
          title={missing ? t("page.notFound") : t("page.loadFailed")}
          action={
            <Button asChild variant="secondary">
              <Link href="/jobs">{t("page.back")}</Link>
            </Button>
          }
        />
      </>
    );
  }

  const current = job.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/jobs"
        className="flex w-fit items-center gap-1 text-muted-foreground text-sm hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t("page.back")}
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="font-semibold text-2xl tracking-tight">{current.title}</h1>
          <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
            <span>{current.reference}</span>
            <Badge tone={STATUS_TONES[current.status]}>{t(`statuses.${current.status}`)}</Badge>
            <span>{t("page.version", { version: current.version })}</span>
            {current.recruiter_name ? (
              <span>{t("page.recruiter", { name: current.recruiter_name })}</span>
            ) : null}
          </div>
        </div>
        {canEdit ? (
          <div className="flex flex-wrap gap-2">
            {statusActions(current.status).map(({ action, to }) => (
              <Button
                key={action}
                variant={action === "open" || action === "resume" ? "primary" : "secondary"}
                disabled={move.isPending}
                onClick={() => move.mutate(to)}
              >
                {t(`actions.${action}`)}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
      {incomplete ? (
        <p role="alert" className="rounded-md bg-warning-subtle p-3 text-sm text-warning">
          {t("incomplete")}
        </p>
      ) : null}
      <Tabs defaultValue="details">
        <TabsList label={current.title}>
          <TabsTrigger value="details">{t("page.tabs.details")}</TabsTrigger>
          <TabsTrigger value="description">{t("page.tabs.description")}</TabsTrigger>
          <TabsTrigger value="history">{t("page.tabs.history")}</TabsTrigger>
        </TabsList>
        <TabsContent value="details">
          <JobForm key={current.version} job={current} readOnly={!canEdit} />
        </TabsContent>
        <TabsContent value="description">
          <DescriptionPanel job={current} canEdit={canEdit} />
        </TabsContent>
        <TabsContent value="history">
          <HistoryPanel jobId={id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
