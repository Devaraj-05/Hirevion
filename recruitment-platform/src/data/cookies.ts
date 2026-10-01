/** A cookie's value from `document.cookie` (or the given cookie string). */
export function readCookie(name: string, jar?: string): string | undefined {
  const cookies = jar ?? (typeof document === "undefined" ? "" : document.cookie);
  for (const part of cookies.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return undefined;
}
