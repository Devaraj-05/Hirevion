"use client";

import { Skeleton } from "@hirevion/ui";
import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { listJobVersions } from "./api";
import { keys } from "./queries";

const REASONS = ["created", "edited", "status", "jd-applied"] as const;

/** Every version of the job, newest first: each change writes one (PRD §12, §97). */
export function HistoryPanel({ jobId }: { jobId: string }) {
  const t = useTranslations("jobs.history");
  const format = useFormatter();
  const versions = useQuery({
    queryKey: keys.versions(jobId),
    queryFn: () => listJobVersions(jobId),
  });

  if (versions.isPending) return <Skeleton className="h-32 w-full" />;
  const rows = [...(versions.data ?? [])].reverse();
  if (rows.length === 0) return <p className="text-muted-foreground text-sm">{t("empty")}</p>;
  return (
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
  );
}
