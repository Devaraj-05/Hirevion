import { cn } from "@hirevion/ui";
import { useId } from "react";

/**
 * The interview's mark (C8-12): an original waveform of five rounded bars on a 24-unit grid. The
 * centre bar is topped by a dot, the "i" of AI. `gradient` is the bar's brand mark (blue into
 * violet, owner's reference 2026-11-24), `ink` sits on plain surfaces, and `light` over camera
 * video. It isn't derived from any product's logo.
 */
const BARS = [
  { x: 4.2, height: 6 },
  { x: 8.1, height: 11 },
  { x: 12, height: 12 },
  { x: 15.9, height: 11 },
  { x: 19.8, height: 6 },
] as const;
const WIDTH = 2.4;
const MIDLINE = 14;

export function Emblem({
  tone = "ink",
  className,
}: {
  tone?: "ink" | "light" | "gradient";
  className?: string;
}) {
  const id = useId();
  const fill = tone === "gradient" ? `url(#${CSS.escape(id)})` : "currentColor";
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      focusable="false"
      className={cn("emblem shrink-0", tone === "light" && "emblem-light", className)}
    >
      {tone === "gradient" ? (
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--brand-from)" />
            <stop offset="1" stopColor="var(--brand-to)" />
          </linearGradient>
        </defs>
      ) : null}
      {BARS.map(({ x, height }) => (
        <rect
          key={x}
          x={x - WIDTH / 2}
          y={MIDLINE - height / 2}
          width={WIDTH}
          height={height}
          rx={WIDTH / 2}
          fill={fill}
        />
      ))}
      <circle cx={12} cy={4.8} r={1.6} fill={fill} />
    </svg>
  );
}

/** The mark on its tile with the wordmark, "AI INTERVIEW". */
export function Wordmark({ label, className }: { label: string; className?: string }) {
  return (
    <span className={cn("flex items-center gap-3", className)}>
      <span className="brand-tile">
        <Emblem tone="gradient" className="size-7" />
      </span>
      <span className="wordmark">{label}</span>
    </span>
  );
}
