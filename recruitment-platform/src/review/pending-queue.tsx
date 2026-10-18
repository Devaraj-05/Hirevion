"use client";

import { Badge, EmptyState, Skeleton } from "@hirevion/ui";
import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { getPendingReviews, reviewKeys } from "./api";

/** The pending-review queue (PRD §71): interviews that have ended and wait for a person to
 * decide, longest waiting first, with what needs a look first (a critical event nobody has
 * reviewed). */
export function PendingQueue() {
  const t = useTranslations("review.queue");
  const format = useFormatter();
  const queue = useQuery({ queryKey: reviewKeys.pending, queryFn: getPendingReviews });
  if (queue.isPending) return <Skeleton className="h-40 w-full" />;
  if (queue.isError || !queue.data) {
    return <EmptyState icon={<ClipboardCheck />} title={t("loadFailed")} />;
  }
  if (queue.data.items.length === 0) {
    return <EmptyState icon={<ClipboardCheck />} title={t("empty")} description={t("emptyHint")} />;
  }
  return (
    <div className="grid gap-3">
      <p className="text-muted-foreground text-sm">{t("count", { count: queue.data.total })}</p>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t("caption")}</caption>
          <thead className="bg-surface-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("candidate")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("job")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("finished")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("evaluation")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("attention")}
              </th>
            </tr>
          </thead>
          <tbody>
            {queue.data.items.map((item) => (
              <tr key={item.interview_id} className="border-border border-t">
                <td className="px-3 py-2">
                  <Link
                    href={`/interviews/${item.interview_id}/review`}
                    aria-label={t("review", { name: item.candidate_name })}
                    className="inline-flex min-h-6 items-center font-medium hover:underline"
                  >
                    {item.candidate_name}
                  </Link>
                  <span className="block text-muted-foreground text-xs">{item.reference}</span>
                </td>
                <td className="px-3 py-2">{item.job_title}</td>
                <td className="px-3 py-2">
                  {item.completed_at
                    ? format.dateTime(new Date(item.completed_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })
                    : "—"}
                </td>
                <td className="px-3 py-2">
                  {/* Whether it is ready, never the AI's score: a reviewer scores first. */}
                  {item.evaluated ? t("evaluated") : t("notEvaluated")}
                </td>
                <td className="px-3 py-2">
                  {item.unreviewed_critical > 0 ? (
                    <Badge tone="danger">
                      {t("critical", { count: item.unreviewed_critical })}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">{t("nothing")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
