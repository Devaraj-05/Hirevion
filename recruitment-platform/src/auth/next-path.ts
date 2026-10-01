/** Where to go after signing in: only a path on this site, and never back to sign-in itself. */

export const HOME_PATH = "/dashboard";

// Backslashes and control characters let some browsers read a path as another host.
// biome-ignore lint/suspicious/noControlCharactersInRegex: matching control characters is the point.
const UNSAFE = /[\\\u0000-\u001f\u007f]/;

export function safeNext(value: string | null | undefined): string {
  if (!value?.startsWith("/") || value.startsWith("//") || UNSAFE.test(value)) return HOME_PATH;
  if (value === "/login" || value.startsWith("/login?") || value.startsWith("/login/"))
    return HOME_PATH;
  return value;
}

export function loginPath(next: string | null | undefined): string {
  const target = safeNext(next);
  return target === HOME_PATH ? "/login" : `/login?next=${encodeURIComponent(target)}`;
}
