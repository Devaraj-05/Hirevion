/** Display preferences kept in cookies, so the server renders them on the first paint. */

export const SIDEBAR_COOKIE = "hv_sidebar";

const ONE_YEAR = 60 * 60 * 24 * 365;

export function writePreference(name: string, value: string): void {
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  // biome-ignore lint/suspicious/noDocumentCookie: a plain display preference the server reads; nothing secret.
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${ONE_YEAR}; samesite=lax${secure}`;
}
