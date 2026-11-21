/**
 * The Content-Security-Policy and baseline security headers for every page (ADR-0012).
 *
 * Scripts run only with this request's nonce ('strict-dynamic' lets them load their own chunks).
 * Inline styles are allowed because Radix positions popovers with style attributes; styles can't
 * run code.
 */

/** `value`'s origin when it is a plain http(s) URL with a host (no wildcard), else null. */
function storageOrigin(value: string | undefined): string | null {
  if (!value || value.includes("*")) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.origin : null;
  } catch {
    return null;
  }
}

/**
 * `storage`: where signed links to blob storage point (`HV_STORAGE_PUBLIC_ORIGIN`): recordings
 * and evidence pictures load from there, so images and media may come from it, and nothing else
 * (C8-8; the review player's media was blocked before).
 */
export function buildCsp(nonce: string, dev: boolean, storage?: string): string {
  const scripts = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  if (dev) {
    scripts.push("'unsafe-eval'"); // React Refresh in `next dev` only
  }
  const origin = storageOrigin(storage);
  const from = origin ? ` ${origin}` : "";
  return [
    "default-src 'self'",
    `script-src ${scripts.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob:${from}`,
    `media-src 'self' blob:${from}`,
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Content-Type-Options": "nosniff",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
};

export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}
