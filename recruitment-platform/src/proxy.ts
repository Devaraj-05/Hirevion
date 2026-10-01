import { type NextRequest, NextResponse } from "next/server";
import { hostConfig, hostKind, internalPath } from "./hosts";
import { buildCsp, newNonce, SECURITY_HEADERS } from "./security/csp";

/**
 * Runs before every page request: sends each host to its own route tree, and sets the CSP (with
 * a fresh nonce Next applies to its scripts) and the other security headers.
 */
export function proxy(request: NextRequest): NextResponse {
  const kind = hostKind(request.headers.get("host"), hostConfig());
  if (kind === "unknown") {
    return new NextResponse(null, { status: 421 });
  }

  const nonce = newNonce();
  const csp = buildCsp(nonce, process.env.NODE_ENV === "development");
  const forwarded = new Headers(request.headers);
  forwarded.set("x-nonce", nonce);
  forwarded.set("content-security-policy", csp);

  // Built from request.url so the rewrite keeps the request's own origin; a different origin
  // would make Next proxy the request over the network instead of rendering it in-process.
  const { pathname, search } = request.nextUrl;
  const url = new URL(`${internalPath(kind, pathname)}${search}`, request.url);
  const response = NextResponse.rewrite(url, { request: { headers: forwarded } });
  response.headers.set("Content-Security-Policy", csp);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    response.headers.set(name, value);
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|api/|favicon.ico|robots.txt).*)"],
};
