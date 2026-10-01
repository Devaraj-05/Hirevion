/** The languages the web app speaks (PRD §102). The choice is a cookie, not part of the URL. */

export const LOCALES = ["en-IN", "en-US"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en-IN";
export const LOCALE_COOKIE = "hv_locale";

export function resolveLocale(value: string | undefined): Locale {
  return LOCALES.find((locale) => locale === value) ?? DEFAULT_LOCALE;
}
