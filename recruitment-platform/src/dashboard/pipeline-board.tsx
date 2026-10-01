"use client";

import { Badge } from "@hirevion/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useId } from "react";
import { PIPELINE_STATUSES, type PipelineCard, type PipelineStatus } from "./model";

interface PipelineBoardProps {
  columns: Partial<Record<PipelineStatus, readonly PipelineCard[]>>;
}

/**
 * The hiring pipeline, a column per PRD §72 status. Each column is a focusable region so the
 * board scrolls by keyboard; moving cards arrives with the data (SP-05, SP-17).
 */
export function PipelineBoard({ columns }: PipelineBoardProps) {
  const t = useTranslations("dashboard.pipeline");
  const format = useFormatter();
  const base = useId();
  return (
    <section aria-labelledby={`${base}-title`}>
      <h2 id={`${base}-title`} className="mb-3 font-semibold">
        {t("title")}
      </h2>
      <ul className="grid auto-cols-[minmax(13rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-2">
        {PIPELINE_STATUSES.map((status) => {
          const cards = columns[status] ?? [];
          const headingId = `${base}-${status}`;
          return (
            <li key={status}>
              <section
                aria-labelledby={headingId}
                // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling board's columns must be reachable by keyboard.
                tabIndex={0}
                className="flex h-full min-h-40 flex-col gap-2 rounded-lg border border-border bg-surface-muted p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 id={headingId} className="font-medium text-sm">
                    {t(`status.${status}`)}
                  </h3>
                  <Badge>{format.number(cards.length)}</Badge>
                </div>
                {cards.length === 0 ? (
                  <p className="text-muted-foreground text-sm">{t("empty")}</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {cards.map((card) => (
                      <li
                        key={card.id}
                        className="rounded-md border border-border bg-surface p-2 text-sm"
                      >
                        <p className="font-medium">{card.name}</p>
                        <p className="text-muted-foreground">{card.job}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
