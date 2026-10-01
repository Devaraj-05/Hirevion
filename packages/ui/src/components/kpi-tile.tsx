import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export interface KpiTileProps {
  label: string;
  /** The formatted value, or null while the metric has no data. */
  value: ReactNode | null;
  /** Read out instead of the value while there is none, e.g. "no data yet". */
  noDataLabel: string;
  hint?: string;
  className?: string;
  /** Shown to sighted users while there is no value. */
  placeholder?: string;
}

/** One metric as a description list: the label is the term, the value its definition. */
export function KpiTile({
  label,
  value,
  noDataLabel,
  hint,
  className,
  placeholder = "—",
}: KpiTileProps) {
  const empty = value === null;
  return (
    <dl
      className={cn(
        "grid gap-1 rounded-lg border border-border bg-surface p-4 shadow-sm",
        className,
      )}
    >
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "text-2xl font-semibold tabular-nums",
          empty ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {empty ? (
          <>
            <span aria-hidden="true">{placeholder}</span>
            <span className="sr-only">{noDataLabel}</span>
          </>
        ) : (
          value
        )}
      </dd>
      {hint ? <dd className="text-xs text-muted-foreground">{hint}</dd> : null}
    </dl>
  );
}
