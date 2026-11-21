"use client";

import { Label, NativeSelect } from "@hirevion/ui";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { InterviewAnalyticsPanel } from "@/interviews/analytics-panel";
import type { Candidate360 } from "@/review/api";

/** Candidate 360's analytics (C8-7, ADR-0047): one interview's dashboard at a time, the latest
 * the candidate took first. */
export function AnalyticsTab({ data }: { data: Candidate360 }) {
  const t = useTranslations("interviews.analytics");
  const id = useId();
  const taken = data.interviews
    .filter((item) => item.started_at !== null)
    .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""));
  const [chosen, setChosen] = useState(taken[0]?.interview_id ?? null);
  if (chosen === null) return <p className="text-muted-foreground text-sm">{t("noInterview")}</p>;
  const current = taken.find((item) => item.interview_id === chosen) ?? taken[0];
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        {taken.length > 1 ? (
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-interview`}>{t("pick")}</Label>
            <NativeSelect
              id={`${id}-interview`}
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
              options={taken.map((item) => ({
                value: item.interview_id,
                label: t("interviewLabel", { reference: item.reference, job: item.job_title }),
              }))}
              className="min-w-72"
            />
          </div>
        ) : (
          <p className="font-medium">
            {current
              ? t("interviewLabel", { reference: current.reference, job: current.job_title })
              : null}
          </p>
        )}
        {current ? (
          <Link
            href={`/interviews/${current.interview_id}`}
            className="text-accent text-sm hover:underline"
          >
            {current.reference}
          </Link>
        ) : null}
      </div>
      <InterviewAnalyticsPanel key={chosen} interviewId={chosen} />
    </div>
  );
}
