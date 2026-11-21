import { cn } from "@hirevion/ui";
import { Check, Lock } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef } from "react";
import { useTranslations } from "use-intl";
import type { StepState } from "../../prepare/steps";

/**
 * One numbered step of the page before the interview. The open step shows its content; a
 * finished one folds to a line saying what was done; a later one waits, dimmed, until the
 * steps above it are done.
 */
export function Step({
  number,
  state,
  title,
  lead,
  summary,
  children,
}: {
  number: number;
  state: StepState;
  title: string;
  lead: string;
  /** The folded line once it is done. */
  summary?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("prepare");
  const id = useId();
  const self = useRef<HTMLElement>(null);
  // The step that opens next comes into view, so the candidate never hunts for it.
  const opened = useRef(state === "active");
  useEffect(() => {
    if (state === "active" && !opened.current) {
      self.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    opened.current = state === "active";
  }, [state]);

  return (
    <section
      ref={self}
      aria-labelledby={`${id}-title`}
      aria-current={state === "active" ? "step" : undefined}
      className={cn(
        "relative scroll-mt-6 scroll-mb-28 rounded-[20px] border bg-surface transition-[opacity,box-shadow] duration-300",
        state === "active"
          ? "border-border/70 shadow-[var(--shadow-md)]"
          : "border-border/60 shadow-none",
        state === "locked" && "opacity-55",
      )}
    >
      <header className="flex items-start gap-4 px-6 py-5">
        <span
          aria-hidden
          className={cn(
            "mt-0.5 grid size-8 shrink-0 place-items-center rounded-full font-semibold text-sm",
            state === "done" && "bg-success text-white dark:text-[#06210f]",
            state === "active" && "bg-accent text-accent-foreground",
            state === "locked" && "bg-surface-sunken text-muted-foreground",
          )}
        >
          {state === "done" ? (
            <Check className="size-4" strokeWidth={3} />
          ) : state === "locked" ? (
            <Lock className="size-3.5" strokeWidth={2.25} />
          ) : (
            number
          )}
        </span>
        <div className="grid min-w-0 flex-1 gap-1">
          <h2 id={`${id}-title`} className="font-semibold text-[1.1rem] leading-snug">
            <span className="sr-only">
              {t("stepLabel", { number, state: t(`state.${state}`) })}{" "}
            </span>
            {title}
          </h2>
          {state === "done" && summary ? (
            <div className="text-[0.92rem] text-muted-foreground">{summary}</div>
          ) : (
            <p className="text-[0.92rem] text-muted-foreground leading-relaxed">{lead}</p>
          )}
        </div>
      </header>
      {state === "active" ? <div className="fade-in grid gap-5 px-6 pb-6">{children}</div> : null}
    </section>
  );
}

/** A check's result as a short line with its state. */
export function ResultLine({
  tone,
  label,
  detail,
}: {
  tone: "pass" | "warn" | "fail" | "pending";
  label: string;
  detail?: string | null;
}) {
  return (
    <li className="flex min-w-0 items-start gap-3 py-2">
      <span
        aria-hidden
        className={cn(
          "mt-1.5 size-2 shrink-0 rounded-full",
          tone === "pass" && "bg-success",
          tone === "warn" && "bg-warning",
          tone === "fail" && "bg-danger",
          tone === "pending" && "animate-pulse bg-muted-foreground/50",
        )}
      />
      <span className="grid min-w-0 gap-0.5">
        <span className="font-medium text-[0.95rem]">{label}</span>
        {detail ? (
          <span className="text-[0.85rem] text-muted-foreground leading-snug">{detail}</span>
        ) : null}
      </span>
    </li>
  );
}

/** Scrolls `element` into view, clear of the floating Start bar (its `scroll-mb-28`). */
export function showAboveBar(element: HTMLElement | null): void {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  element?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
}
