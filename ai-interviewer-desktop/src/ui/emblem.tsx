import { cn } from "@hirevion/ui";

/**
 * The interview's mark (C8-12): an original waveform of five rounded bars on a 24-unit grid. The
 * centre bar is topped by a dot, the "i" of AI. `ink` sits on the app's surfaces, `light` over
 * camera video (translucent white with a soft shadow). It isn't derived from any product's logo.
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
  tone?: "ink" | "light";
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      focusable="false"
      className={cn("emblem shrink-0", tone === "light" && "emblem-light", className)}
    >
      {BARS.map(({ x, height }) => (
        <rect
          key={x}
          x={x - WIDTH / 2}
          y={MIDLINE - height / 2}
          width={WIDTH}
          height={height}
          rx={WIDTH / 2}
          fill="currentColor"
        />
      ))}
      <circle cx={12} cy={4.8} r={1.6} fill="currentColor" />
    </svg>
  );
}

/** The mark with its wordmark, "AI INTERVIEW", tracked in small caps. */
export function Wordmark({ label, className }: { label: string; className?: string }) {
  return (
    <span className={cn("flex items-center gap-2", className)}>
      <Emblem className="size-[22px] text-foreground" />
      <span className="wordmark">{label}</span>
    </span>
  );
}
