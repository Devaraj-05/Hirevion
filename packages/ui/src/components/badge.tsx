import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { cn } from "../lib/cn";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-surface-sunken text-muted-foreground",
        accent: "bg-accent-subtle text-accent-subtle-foreground",
        success: "bg-success-subtle text-success",
        warning: "bg-warning-subtle text-warning",
        danger: "bg-danger-subtle text-danger",
        info: "bg-info-subtle text-info",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeTone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;

export function Badge({
  className,
  tone = "neutral",
  ...props
}: ComponentProps<"span"> & { tone?: BadgeTone }) {
  return <span data-tone={tone} className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export type Severity = "INFO" | "WARNING" | "CRITICAL";

const severityClass: Record<Severity, string> = {
  INFO: "bg-sev-info-subtle text-sev-info",
  WARNING: "bg-sev-warning-subtle text-sev-warning",
  CRITICAL: "bg-sev-critical-subtle text-sev-critical",
};

/** A proctoring severity (PRD §64). The label is always shown, so colour is never the only cue. */
export function SeverityBadge({ severity, label }: { severity: Severity; label: string }) {
  return (
    <span
      data-severity={severity}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide",
        severityClass[severity],
      )}
    >
      {label}
    </span>
  );
}
