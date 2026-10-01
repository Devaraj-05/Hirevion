/**
 * The Content-Security-Policy and baseline security headers for every page (ADR-0012).
 *
 * Scripts run only with this request's nonce ('strict-dynamic' lets them load their own chunks).
 * Inline styles are allowed because Radix positions popovers with style attributes; styles can't
 * run code.
 */

export function buildCsp(nonce: string, dev: boolean): string {
  const scripts = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  if (dev) {
    scripts.push("'unsafe-eval'"); // React Refresh in `next dev` only
  }
  return [
    "default-src 'self'",
    `script-src ${scripts.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
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
