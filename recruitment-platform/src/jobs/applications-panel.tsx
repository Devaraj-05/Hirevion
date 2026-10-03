"use client";

import { Badge, Skeleton } from "@hirevion/ui";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { listApplications } from "@/candidates/api";
import { FlagBadges } from "@/candidates/flags";
import { keys } from "@/candidates/queries";
import { Pager } from "@/data/pager";
import { useCursorPage } from "@/data/use-cursor-page";

const PAGE_SIZE = 25;

/** The job's candidates, from the resumes uploaded to it; screening (SP-05) moves their stage. */
export function ApplicationsPanel({ jobId }: { jobId: string }) {
  const t = useTranslations("jobs.applications");
  const stages = useTranslations("candidates.stages");
  const format = useFormatter();
  const page = useCursorPage(keys.applications(jobId), (cursor) =>
    listApplications(jobId, { cursor, limit: PAGE_SIZE }),
  );

  if (page.isLoading) return <Skeleton className="h-32 w-full" />;
  if (page.rows.length === 0) return <p className="text-muted-foreground text-sm">{t("empty")}</p>;
  return (
    <div className="grid gap-2">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("caption")}</caption>
          <thead className="bg-surface-muted">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                {t("name")}
              </th>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                {t("skills")}
              </th>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                {t("stage")}
              </th>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                {t("applied")}
              </th>
            </tr>
          </thead>
          <tbody>
            {page.rows.map((application) => (
              <tr key={application.id} className="border-border border-t align-top">
                <td className="px-3 py-2">
                  <Link
                    href={`/candidates/${application.candidate.id}`}
                    className="font-medium hover:underline"
                  >
                    {application.candidate.name}
                  </Link>
                  {application.candidate.headline ? (
                    <div className="text-muted-foreground text-xs">
                      {application.candidate.headline}
                    </div>
                  ) : null}
                  <FlagBadges flags={application.candidate.flags} />
                </td>
                <td className="px-3 py-2">{application.candidate.skills.join(", ") || "—"}</td>
                <td className="px-3 py-2">
                  <Badge>{stages(application.stage)}</Badge>
                </td>
                <td className="px-3 py-2">
                  {format.dateTime(new Date(application.created_at), { dateStyle: "medium" })}
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
