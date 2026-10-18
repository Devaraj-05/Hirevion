"use client";

import { Badge, NativeSelect } from "@hirevion/ui";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { PIPELINE_STATUSES, type PipelineCard, type PipelineStatus } from "./model";

interface PipelineBoardProps {
  columns: Partial<Record<PipelineStatus, readonly PipelineCard[]>>;
  /** How many each column holds in all, when more than its cards are shown. */
  counts?: Partial<Record<PipelineStatus, number>>;
  /** Asks to move a card to a status it allows (PRD §72). Without it the board is a view. */
  onMove?: (card: PipelineCard, to: PipelineStatus) => void;
}

/**
 * The hiring pipeline, a column per PRD §72 status. Each column is a focusable region so the
 * board scrolls by keyboard. A card that may move has a "Move to" menu (the way to move it by
 * keyboard or touch) and can also be dragged to a column it allows; the move itself is the
 * status change, which says why where a reason is needed.
 */
export function PipelineBoard({ columns, counts, onMove }: PipelineBoardProps) {
  const t = useTranslations("dashboard.pipeline");
  const format = useFormatter();
  const base = useId();
  const [dragged, setDragged] = useState<PipelineCard | null>(null);
  return (
    <section aria-labelledby={`${base}-title`}>
      <h2 id={`${base}-title`} className="mb-3 font-semibold">
        {t("title")}
      </h2>
      <ul className="grid auto-cols-[minmax(13rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-2">
        {PIPELINE_STATUSES.map((status) => {
          const cards = columns[status] ?? [];
          const total = counts?.[status] ?? cards.length;
          const headingId = `${base}-${status}`;
          const accepts = dragged?.moves?.includes(status) ?? false;
          return (
            <li key={status}>
              <section
                aria-labelledby={headingId}
                // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling board's columns must be reachable by keyboard.
                tabIndex={0}
                onDragOver={(event) => {
                  if (accepts) event.preventDefault();
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  if (dragged && accepts) onMove?.(dragged, status);
                  setDragged(null);
                }}
                className={`flex h-full min-h-40 flex-col gap-2 rounded-lg border bg-surface-muted p-3 ${
                  accepts ? "border-accent" : "border-border"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 id={headingId} className="font-medium text-sm">
                    {t(`status.${status}`)}
                  </h3>
                  <Badge>{format.number(total)}</Badge>
                </div>
                {cards.length === 0 ? (
                  <p className="text-muted-foreground text-sm">{t("empty")}</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {cards.map((card) => {
                      const moves = onMove ? (card.moves ?? []) : [];
                      return (
                        <li
                          key={card.id}
                          draggable={moves.length > 0}
                          onDragStart={() => setDragged(card)}
                          onDragEnd={() => setDragged(null)}
                          className="rounded-md border border-border bg-surface p-2 text-sm"
                        >
                          {card.href ? (
                            <Link href={card.href} className="font-medium hover:underline">
                              {card.name}
                            </Link>
                          ) : (
                            <p className="font-medium">{card.name}</p>
                          )}
                          <p className="text-muted-foreground">{card.job}</p>
                          {moves.length > 0 ? (
                            <NativeSelect
                              className="mt-2"
                              aria-label={t("move", { name: card.name })}
                              value=""
                              onChange={(event) => {
                                const to = event.target.value as PipelineStatus;
                                if (to) onMove?.(card, to);
                              }}
                              options={[
                                { value: "", label: t("moveTo") },
                                ...moves.map((to) => ({ value: to, label: t(`status.${to}`) })),
                              ]}
                            />
                          ) : null}
                        </li>
                      );
                    })}
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
