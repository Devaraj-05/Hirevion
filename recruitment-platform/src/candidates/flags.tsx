"use client";

import { Badge } from "@hirevion/ui";
import { useTranslations } from "next-intl";

/** The flags the pipeline sets that a recruiter should see, most serious first. */
const SHOWN = [
  "injection",
  "injection_removed",
  "hidden_text",
  "metadata_text",
  "possible_duplicate_of",
  "low_ocr_confidence",
  "zero_width",
  "duplicate_of",
] as const;
type Shown = (typeof SHOWN)[number];
const WARNINGS: ReadonlySet<Shown> = new Set([
  "injection",
  "injection_removed",
  "hidden_text",
  "metadata_text",
]);
/** Flags that are counts: none of them is nothing to show. (A confidence of 0 is the worst
 * reading, and is shown.) */
const COUNTS: ReadonlySet<Shown> = new Set(["injection_removed", "zero_width"]);

export function shownFlags(flags: Record<string, unknown> | null | undefined): Shown[] {
  if (!flags) return [];
  return SHOWN.filter((flag) => {
    const value = flags[flag];
    if (value === undefined || value === null || value === false) return false;
    return !(COUNTS.has(flag) && value === 0);
  });
}

/** Compact badges, for lists. */
export function FlagBadges({ flags }: { flags: Record<string, unknown> | null | undefined }) {
  const t = useTranslations("candidates.flags");
  const shown = shownFlags(flags);
  if (shown.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1">
      {shown.map((flag) => (
        <li key={flag}>
          <Badge tone={WARNINGS.has(flag) ? "warning" : "info"}>{t(flag)}</Badge>
        </li>
      ))}
    </ul>
  );
}

/** The full list, for a candidate's page; injection phrases are quoted so a reader can judge. */
export function FlagWarnings({
  flags,
  label,
}: {
  flags: Record<string, unknown> | null | undefined;
  label: string;
}) {
  const t = useTranslations("candidates.flags");
  const shown = shownFlags(flags);
  if (shown.length === 0) return null;
  const phrases = Array.isArray(flags?.injection) ? (flags.injection as string[]) : [];
  return (
    <section
      aria-label={label}
      className="grid gap-1 rounded-md bg-warning-subtle p-3 text-sm text-warning"
    >
      <ul className="grid gap-1">
        {shown.map((flag) => (
          <li key={flag}>
            {t(flag)}
            {flag === "injection" && phrases.length > 0
              ? ` (${phrases.map((phrase) => `“${phrase}”`).join(", ")})`
              : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
