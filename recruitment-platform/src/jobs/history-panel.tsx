"use client";

import { Skeleton } from "@hirevion/ui";
import { useFormatter, useTranslations } from "next-intl";
import { Pager } from "@/data/pager";
import { QueryFailed } from "@/data/query-failed";
import { useCursorPage } from "@/data/use-cursor-page";
import { listJobVersions } from "./api";
import { keys } from "./queries";

const REASONS = ["created", "edited", "status", "jd-applied"] as const;
const PAGE_SIZE = 25;

/** Every version of the job, newest first: each change writes one (PRD §12, §97). */
export function HistoryPanel({ jobId }: { jobId: string }) {
  const t = useTranslations("jobs.history");
  const format = useFormatter();
  const page = useCursorPage(keys.versions(jobId), (cursor) =>
    listJobVersions(jobId, { cursor, limit: PAGE_SIZE }),
  );

  if (page.isLoading) return <Skeleton className="h-32 w-full" />;
  if (page.error && page.rows.length === 0) return <QueryFailed onRetry={page.refetch} />;
  const rows = page.rows;
  if (rows.length === 0) return <p className="text-muted-foreground text-sm">{t("empty")}</p>;
  return (
    <div className="grid gap-2">
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <caption className="sr-only">{t("caption")}</caption>
        <thead className="bg-surface-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("version")}
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("reason")}
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("when")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((version) => (
            <tr key={version.version} className="border-border border-t">
              <td className="px-3 py-2">{version.version}</td>
              <td className="px-3 py-2">
                {(REASONS as readonly string[]).includes(version.reason)
                  ? t(`reasons.${version.reason as (typeof REASONS)[number]}`)
                  : version.reason}
              </td>
              <td className="px-3 py-2">
                {format.dateTime(new Date(version.created_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <Pager
      hasPrevious={page.hasPrevious}
      hasNext={page.hasNext}
      onPrevious={page.previousPage}
      onNext={page.nextPage}
    />
    </div>
  );
}
