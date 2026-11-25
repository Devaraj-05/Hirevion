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
      <h2 id={`${base}-title`} className="mb-3 font-semibold text-lg">
        {t("title")}
      </h2>
      {/* Columns keep one height and scroll on their own: a long column no longer stretches the
          page past 3,000 px (owner's review, 2026-11-26). */}
      <ul className="grid auto-cols-[minmax(15rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-2">
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
                className={`flex h-full max-h-[34rem] min-h-40 flex-col gap-2.5 rounded-2xl border bg-surface-sunken/60 p-2.5 ${
                  accepts ? "border-accent" : "border-transparent"
                }`}
              >
                <div className="flex items-center justify-between gap-2 px-1.5 pt-1">
                  <h3 id={headingId} className="font-semibold text-[0.85rem]">
                    {t(`status.${status}`)}
                  </h3>
                  <Badge>{format.number(total)}</Badge>
                </div>
                {cards.length === 0 ? (
                  <p className="px-1.5 text-muted-foreground text-sm">{t("empty")}</p>
                ) : (
                  <ul className="-mx-1 flex min-h-0 flex-col gap-2 overflow-y-auto px-1 pb-1">
                    {cards.map((card) => {
                      const moves = onMove ? (card.moves ?? []) : [];
                      return (
                        <li
                          key={card.id}
                          draggable={moves.length > 0}
                          onDragStart={() => setDragged(card)}
                          onDragEnd={() => setDragged(null)}
                          className="rounded-xl border border-border/70 bg-surface p-3 text-sm shadow-[var(--shadow-sm)]"
                        >
                          {card.href ? (
                            <Link href={card.href} className="font-medium hover:underline">
                              {card.name}
                            </Link>
                          ) : (
                            <p className="font-medium">{card.name}</p>
                          )}
                          <p className="truncate text-[0.8rem] text-muted-foreground">{card.job}</p>
                          {moves.length > 0 ? (
                            <NativeSelect
                              className="mt-2.5 h-8 text-xs"
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
