/** Where the portal goes after signing in: only a portal path, never back to sign-in. */

export const PORTAL_HOME = "/";

// Backslashes and control characters let some browsers read a path as another host.
// biome-ignore lint/suspicious/noControlCharactersInRegex: matching control characters is the point.
const UNSAFE = /[\\\u0000-\u001f\u007f]/;

export function safePortalNext(value: string | null | undefined): string {
  if (!value?.startsWith("/") || value.startsWith("//") || UNSAFE.test(value)) return PORTAL_HOME;
  if (value === "/login" || value.startsWith("/login?") || value.startsWith("/login/")) {
    return PORTAL_HOME;
  }
  return value;
}

export function portalLoginPath(next: string | null | undefined): string {
  const target = safePortalNext(next);
  return target === PORTAL_HOME ? "/login" : `/login?next=${encodeURIComponent(target)}`;
}
