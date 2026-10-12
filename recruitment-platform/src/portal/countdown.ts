/** The interview window's countdown (master plan §6.3 "Interview status and window"). */

export type Phase = "before" | "open" | "closed";
export type Unit = "days" | "hours" | "minutes" | "seconds";

/** Where `now` falls against the window, and how long until its next edge. */
export function windowPhase(
  now: number,
  opensAt: number,
  closesAt: number,
): { phase: Phase; ms: number } {
  if (now < opensAt) return { phase: "before", ms: opensAt - now };
  if (now < closesAt) return { phase: "open", ms: closesAt - now };
  return { phase: "closed", ms: 0 };
}

const UNITS: [Unit, number][] = [
  ["days", 86_400_000],
  ["hours", 3_600_000],
  ["minutes", 60_000],
  ["seconds", 1_000],
];

/** `ms` as its two largest non-zero units, from the largest present ("1 day 2 hours"). */
export function countdownParts(ms: number): [Unit, number][] {
  let rest = Math.max(0, ms);
  const parts: [Unit, number][] = [];
  for (const [unit, size] of UNITS) {
    const value = Math.floor(rest / size);
    rest -= value * size;
    if (parts.length > 0 || value > 0) parts.push([unit, value]);
    if (parts.length === 2) break;
  }
  if (parts.length === 0) return [["seconds", 0]];
  return parts.filter(([, value], index) => index === 0 || value > 0);
}
