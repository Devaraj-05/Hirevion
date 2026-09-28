/**
 * The pairing token from the page's URL fragment (`#t=...`). The fragment never leaves the
 * phone, so the token stays out of server and proxy logs.
 */
export function readToken(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("t");
  return token ? token : null;
}

/** Automated tests add `auto=1` to start the camera without a tap. */
export function wantsAutoStart(hash: string): boolean {
  return new URLSearchParams(hash.replace(/^#/, "")).get("auto") === "1";
}
