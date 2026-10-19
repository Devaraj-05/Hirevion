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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, SearchX } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { useAdminProblem } from "@/admin/problems";
import { QueryFailed } from "@/data/query-failed";
import { getSkillMatrix, getTemplate, listTemplateVersions, setTemplateArchived } from "./api";
import { keys, MatrixTable, TemplateForm } from "./template-form";

/** One interview template: its settings (each save a new version), the current version's skill
 * matrix, and every version, which stay as they were for the interviews that pinned them. */
export function TemplatePage({ id, canManage }: { id: string; canManage: boolean }) {
  const t = useTranslations("interviews.templates");
  const titles = useTranslations("routes");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const template = useQuery({ queryKey: keys.template(id), queryFn: () => getTemplate(id) });
  // A tab is mounted when first opened and kept, so settings half-edited survive a look at
  // another tab.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set(["settings"]));
  const archive = useMutation({
    mutationFn: (archived: boolean) => setTemplateArchived(id, archived),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.template(id), saved);
      void queryClient.invalidateQueries({ queryKey: keys.list });
      toast.success(t(saved.status === "archived" ? "archived" : "restored"), {});
    },
    onError: problems.show,
  });

  const placeholderTitle = <h1 className="sr-only">{titles("interviewTemplatesDetail")}</h1>;
  if (template.isPending) {
    return (
      <>
        {placeholderTitle}
        <Skeleton className="h-64 w-full" />
      </>
    );
  }
  if (template.isError) {
    const missing = isApiProblem(template.error) && template.error.status === 404;
    return (
      <>
        {placeholderTitle}
        <EmptyState
          icon={<SearchX />}
          title={missing ? t("notFound") : t("loadFailed")}
          action={
            <Button asChild variant="secondary">
              <Link href="/interviews/templates">{t("back")}</Link>
            </Button>
          }
        />
      </>
    );
  }

  const current = template.data;
  const archived = current.status === "archived";
  const keep = (tab: string) => (opened.has(tab) ? { forceMount: true as const } : {});
  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/interviews/templates"
        className="flex w-fit items-center gap-1 text-muted-foreground text-sm hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t("back")}
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="font-semibold text-2xl tracking-tight">{current.name}</h1>
          <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
            <Badge tone={archived ? "neutral" : "success"}>{t(`statuses.${current.status}`)}</Badge>
            <span>{t("version", { version: current.version })}</span>
          </div>
        </div>
        {canManage ? (
          <Button
            variant="secondary"
            disabled={archive.isPending}
            onClick={() => archive.mutate(!archived)}
          >
            {archived ? t("restore") : t("archive")}
          </Button>
        ) : null}
      </div>
      {archived ? <p className="text-muted-foreground text-sm">{t("archivedNote")}</p> : null}
      <Tabs
        defaultValue="settings"
        onValueChange={(value) => setOpened((previous) => new Set(previous).add(value))}
      >
        <TabsList label={current.name}>
          <TabsTrigger value="settings">{t("tabs.settings")}</TabsTrigger>
          <TabsTrigger value="matrix">{t("tabs.matrix")}</TabsTrigger>
          <TabsTrigger value="versions">{t("tabs.versions")}</TabsTrigger>
        </TabsList>
        <TabsContent value="settings" {...keep("settings")}>
          <TemplateForm template={current} canManage={canManage} />
        </TabsContent>
        <TabsContent value="matrix" {...keep("matrix")}>
          <SavedMatrix id={id} version={current.version} />
        </TabsContent>
        <TabsContent value="versions" {...keep("versions")}>
          <Versions id={id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SavedMatrix({ id, version }: { id: string; version: number }) {
  const rows = useQuery({
    queryKey: [...keys.matrix(id), version],
    queryFn: () => getSkillMatrix(id),
  });
  return <MatrixTable rows={rows.data} pending={rows.isPending} failed={rows.isError} />;
}

function Versions({ id }: { id: string }) {
  const t = useTranslations("interviews.templates");
  const settings = useTranslations("interviews.settings");
  const format = useFormatter();
  const versions = useQuery({
    queryKey: keys.versions(id),
    queryFn: () => listTemplateVersions(id),
  });
  if (versions.isError) return <QueryFailed onRetry={() => void versions.refetch()} />;
  if (!versions.data) return <Skeleton className="h-32 w-full" />;
  return (
    <ol className="grid gap-3" aria-label={t("tabs.versions")}>
      {[...versions.data].reverse().map((version) => (
        <li
          key={version.version}
          className="grid gap-1 rounded-md border border-border p-3 text-sm"
        >
          <span className="font-medium">
            {t("versionLine", {
              version: version.version,
              date: format.dateTime(new Date(version.created_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })}
          </span>
          <span className="text-muted-foreground">
            {t("versionSummary", {
              minutes: version.duration_minutes,
              count: version.question_count,
              proctoring: settings(`levels.${version.proctoring_level}`),
              thirdEye: settings(`thirdEyeModes.${version.third_eye}`),
            })}
          </span>
          <span className="text-muted-foreground">
            {version.skills.map((skill) => `${skill.name} ${skill.weight}%`).join(" · ")}
          </span>
        </li>
      ))}
    </ol>
  );
}
