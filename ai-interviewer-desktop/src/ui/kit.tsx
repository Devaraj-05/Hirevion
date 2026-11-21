import { Button, cn } from "@hirevion/ui";
import type { ComponentProps, ReactNode } from "react";

/**
 * The candidate app's shared pieces (product owner, 2026-11-16: a calm, Apple-like look). They
 * sit on the design system's components and tokens and set this app's shape: pill buttons,
 * 20 px panels, 12 px fields.
 */

type Tone = "neutral" | "success" | "warning" | "danger" | "accent";

const PILL_SIZES = { md: "h-10 px-5 text-[0.95rem]", lg: "h-12 px-7 text-base" } as const;
const PILL_VARIANTS = {
  primary: "",
  secondary: "border-border bg-surface shadow-sm",
  quiet: "text-accent hover:bg-accent-subtle",
  danger: "",
} as const;

/** The app's button: a pill that presses in at once (feedback on pointer-down). */
export function PillButton({
  variant = "primary",
  size = "md",
  className,
  ...props
}: Omit<ComponentProps<typeof Button>, "variant" | "size"> & {
  variant?: keyof typeof PILL_VARIANTS;
  size?: keyof typeof PILL_SIZES;
}) {
  const kit = variant === "quiet" ? "ghost" : variant;
  return (
    <Button
      variant={kit}
      className={cn(
        "rounded-full font-medium transition-[transform,background-color,opacity] duration-150 active:scale-[0.97] motion-reduce:active:scale-100",
        PILL_SIZES[size],
        PILL_VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}

/** A surface that groups one task. */
export function Panel({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "rounded-[20px] border border-border/70 bg-surface shadow-[var(--shadow-md)]",
        className,
      )}
      {...props}
    />
  );
}

/** A screen's heading and its one line of guidance. */
export function ScreenTitle({
  id,
  title,
  lead,
  className,
}: {
  id?: string;
  title: ReactNode;
  lead?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-2", className)}>
      <h1 id={id} className="font-semibold text-[1.75rem] leading-tight">
        {title}
      </h1>
      {lead ? <p className="max-w-[60ch] text-muted-foreground leading-relaxed">{lead}</p> : null}
    </div>
  );
}

const PILL_TONES: Record<Tone, string> = {
  neutral: "bg-surface-sunken text-muted-foreground",
  success: "bg-success-subtle text-success",
  warning: "bg-warning-subtle text-warning",
  danger: "bg-danger-subtle text-danger",
  accent: "bg-accent-subtle text-accent-subtle-foreground",
};
const DOT_TONES: Record<Tone, string> = {
  neutral: "bg-muted-foreground",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  accent: "bg-accent",
};

/** A live state in a few words (connected, recording): the dot carries the state's colour, the
 * words carry its meaning. */
export function StatusPill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-2 whitespace-nowrap rounded-full px-3 font-medium text-[0.8rem]",
        PILL_TONES[tone],
      )}
    >
      <span className={cn("size-1.5 rounded-full", DOT_TONES[tone])} aria-hidden />
      {children}
    </span>
  );
}

/** Something the candidate should know or do, said once and plainly. */
export function Notice({
  tone = "warning",
  role = "status",
  className,
  children,
}: {
  tone?: Exclude<Tone, "neutral">;
  role?: "status" | "alert";
  className?: string;
  children: ReactNode;
}) {
  return (
    <p
      role={role}
      className={cn(
        "fade-in rounded-2xl px-4 py-3 text-[0.9rem] leading-snug",
        PILL_TONES[tone],
        className,
      )}
    >
      {children}
    </p>
  );
}
