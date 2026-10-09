import type { ReactNode } from "react";
import { IntlProvider } from "use-intl";
import enIN from "./en-IN.json";
import enUS from "./en-US.json";

/** The desktop app's languages (PRD §102): en-IN first, then en-US. */
export const CATALOGUES = { "en-IN": enIN, "en-US": enUS } as const;
export type Locale = keyof typeof CATALOGUES;
export const DEFAULT_LOCALE: Locale = "en-IN";

/** The candidate's language when known, else Windows', else en-IN. */
export function pickLocale(preferred: readonly string[]): Locale {
  for (const tag of preferred) {
    if (tag in CATALOGUES) return tag as Locale;
    if (tag.toLowerCase().startsWith("en-us")) return "en-US";
  }
  return DEFAULT_LOCALE;
}

export function I18nProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  return (
    <IntlProvider locale={locale} messages={CATALOGUES[locale]} timeZone={localTimeZone()}>
      {children}
    </IntlProvider>
  );
}

function localTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
}
