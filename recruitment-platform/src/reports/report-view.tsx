"use client";

import { Badge } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useId } from "react";
import type { ReportBlock, ReportDocument, ReportSection } from "./api";

/** A report document (SP-17): its sections of blocks, as the server's PDF shows them. Every string
 * is data from the API, rendered as text. */
export function ReportView({
  document,
  compact = false,
}: {
  document: ReportDocument;
  /** Without the confidential banner and the contents list, for a few sections inside a page. */
  compact?: boolean;
}) {
  const t = useTranslations("reports.view");
  const base = useId();
  return (
    <article className="flex flex-col gap-6" aria-label={document.title}>
      {document.confidential && !compact ? (
        <p className="w-fit rounded-md border border-danger px-3 py-1 font-semibold text-danger text-xs uppercase tracking-wide">
          {t("confidential")}
        </p>
      ) : null}
      {document.sections.length > 1 && !compact ? (
        <nav aria-label={t("contents")} className="rounded-lg bg-surface-muted p-4">
          <h2 className="mb-2 font-semibold text-sm">{t("contents")}</h2>
          <ol className="grid list-decimal gap-1 pl-5 text-sm sm:grid-cols-2">
            {document.sections.map((section) => (
              <li key={section.key}>
                <a href={`#${base}-${section.key}`} className="underline-offset-2 hover:underline">
                  {section.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      ) : null}
      {document.sections.map((section) => (
        <Section key={section.key} section={section} anchor={`${base}-${section.key}`} />
      ))}
    </article>
  );
}

function Section({ section, anchor }: { section: ReportSection; anchor: string }) {
  const t = useTranslations("reports.view");
  return (
    <section
      id={anchor}
      aria-labelledby={`${anchor}-title`}
      data-section={section.key}
      data-status={section.status}
      className="grid gap-3 scroll-mt-20"
    >
      <h2
        id={`${anchor}-title`}
        className="flex items-center gap-2 border-border border-b pb-1 font-semibold text-lg"
      >
        {section.title}
        {section.status === "populated" ? null : (
          <Badge tone={section.status === "pending" ? "warning" : "neutral"}>
            {t(`status.${section.status}`)}
          </Badge>
        )}
      </h2>
      {section.note ? <p className="text-muted-foreground text-sm italic">{section.note}</p> : null}
      {section.blocks.map((block, index) => (
        // The blocks have no ids; a section's blocks never reorder.
        // biome-ignore lint/suspicious/noArrayIndexKey: static, ordered content.
        <Block key={index} block={block} />
      ))}
    </section>
  );
}

function Block({ block }: { block: ReportBlock }) {
  const t = useTranslations("reports.view");
  switch (block.type) {
    case "text":
      return (
        <p className={block.tone === "muted" ? "text-muted-foreground text-sm" : "text-sm"}>
          {block.text}
        </p>
      );
    case "list":
      return (
        <ul className="grid list-disc gap-1 pl-5 text-sm">
          {block.items.map((item, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static, ordered content.
            <li key={index}>{item}</li>
          ))}
        </ul>
      );
    case "facts":
      return (
        <dl className="grid grid-cols-[minmax(8rem,14rem)_1fr] gap-x-4 gap-y-1 text-sm">
          {block.rows.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="break-words">{row.value}</dd>
            </div>
          ))}
        </dl>
      );
    case "table":
      return (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <caption className="px-3 py-2 text-left font-medium">{block.caption}</caption>
            <thead className="bg-surface-muted">
              <tr>
                {block.columns.map((column) => (
                  <th key={column} scope="col" className="px-3 py-2 font-medium">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.length === 0 ? (
                <tr className="border-border border-t">
                  <td colSpan={block.columns.length} className="px-3 py-2 text-muted-foreground">
                    {t("nothingToList")}
                  </td>
                </tr>
              ) : (
                block.rows.map((row, index) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: static, ordered rows.
                  <tr key={index} className="border-border border-t align-top">
                    {row.map((cell, cellIndex) => (
                      // biome-ignore lint/suspicious/noArrayIndexKey: static, ordered cells.
                      <td key={cellIndex} className="px-3 py-2 break-words">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      );
    case "quotes":
      return (
        <div className="grid gap-2">
          {block.items.map((item, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static, ordered content.
            <blockquote key={index} className="border-border border-l-4 pl-3 text-sm">
              <p>{`“${item.text}”`}</p>
              <cite className="text-muted-foreground text-xs not-italic">{item.source}</cite>
            </blockquote>
          ))}
        </div>
      );
    case "notice":
      return (
        <p
          role="note"
          className={
            block.tone === "warning"
              ? "rounded-md border border-warning bg-warning-subtle px-3 py-2 text-sm"
              : "rounded-md border border-border bg-surface-muted px-3 py-2 text-sm"
          }
        >
          {block.text}
        </p>
      );
    case "code":
      return (
        <figure className="grid gap-1">
          {block.caption ? (
            <figcaption className="font-medium text-sm">{block.caption}</figcaption>
          ) : null}
          <pre
            // biome-ignore lint/a11y/noNoninteractiveTabindex: a code block that scrolls must be reachable by keyboard.
            tabIndex={0}
            className="overflow-x-auto rounded-md bg-surface-muted p-3 text-xs"
          >
            <code>{block.text}</code>
          </pre>
        </figure>
      );
    default:
      return null;
  }
}
