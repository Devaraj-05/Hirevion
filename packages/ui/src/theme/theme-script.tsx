// Rendered on the server into <head>, so it runs before the page paints: no flash of the wrong
// theme. Kept apart from `useTheme` (a client hook) so it stays a server component.

export const THEME_STORAGE_KEY = "hv_theme";
export const DARK_QUERY = "(prefers-color-scheme: dark)";

export type ThemePreference = "light" | "dark" | "system";

/** The script that applies the stored theme (light, dark, or the system's) to <html>. */
export function themeScript(): string {
  return `(function(){try{var p=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});var d=p==="dark"||(p!=="light"&&window.matchMedia(${JSON.stringify(DARK_QUERY)}).matches);document.documentElement.dataset.theme=d?"dark":"light";}catch(e){document.documentElement.dataset.theme="light";}})();`;
}

/** Put in <head>; the nonce lets it run under the Content-Security-Policy. */
export function ThemeScript({ nonce }: { nonce?: string | undefined }) {
  // biome-ignore lint/security/noDangerouslySetInnerHtml: a fixed script with no user input, run before paint
  return <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript() }} />;
}
