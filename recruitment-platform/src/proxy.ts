import { type NextRequest, NextResponse } from "next/server";
import { routeFor } from "./auth/manifest";
import { loginPath } from "./auth/next-path";
import { can } from "./auth/permissions";
import { PATH_HEADER, resolveSession } from "./auth/session";
import { hostConfig, hostKind, internalPath } from "./hosts";
import { buildCsp, newNonce, SECURITY_HEADERS } from "./security/csp";

const FORBIDDEN_PAGE = "/recruiter/forbidden";

/**
 * Runs before every page request:
 * - sends each host to its own route tree;
 * - answers early for guarded recruiter pages: anonymous visitors go to sign in, and a session
 *   without the route's permission gets the Forbidden page with 403. The pages check again
 *   themselves, so this is never the only check;
 * - sets the CSP (with a fresh nonce Next applies to its scripts) and the other security headers.
 */
export async function proxy(request: NextRequest): Promise<NextResponse> {
  const kind = hostKind(request.headers.get("host"), hostConfig());
  if (kind === "unknown") {
    return new NextResponse(null, { status: 421 });
  }

  const nonce = newNonce();
  const csp = buildCsp(nonce, process.env.NODE_ENV === "development");
  const { pathname, search } = request.nextUrl;

  let target = `${internalPath(kind, pathname)}${search}`;
  let status = 200;
  const route = kind === "recruiter" ? routeFor(decodePath(pathname)) : undefined;
  if (route) {
    const cookies = Object.fromEntries(
      request.cookies.getAll().map((cookie) => [cookie.name, cookie.value]),
    );
    const session = await resolveSession(cookies, process.env);
    if (!session) {
      const login = browserUrl(request, loginPath(`${pathname}${search}`));
      return secure(NextResponse.redirect(login, 307), csp);
    }
    if (!can(session, route.permission)) {
      target = FORBIDDEN_PAGE;
      status = 403;
    }
  }

  const forwarded = new Headers(request.headers);
  forwarded.set("x-nonce", nonce);
  forwarded.set("content-security-policy", csp);
  forwarded.set(PATH_HEADER, `${pathname}${search}`);

  // Built from request.url so the rewrite keeps the request's own origin; a different origin
  // would make Next proxy the request over the network instead of rendering it in-process.
  const url = new URL(target, request.url);
  return secure(NextResponse.rewrite(url, { status, request: { headers: forwarded } }), csp);
}

/**
 * A URL on the host the browser asked for. request.url carries Next's own fallback host instead;
 * the Host header is safe to use because hostKind has already matched it against the allow-list.
 */
function browserUrl(request: NextRequest, path: string): URL {
  const host = request.headers.get("host") ?? request.nextUrl.host;
  const forwarded = request.headers.get("x-forwarded-proto");
  const protocol =
    forwarded === "https" || forwarded === "http" ? `${forwarded}:` : request.nextUrl.protocol;
  return new URL(path, `${protocol}//${host}`);
}

function secure(response: NextResponse, csp: string): NextResponse {
  response.headers.set("Content-Security-Policy", csp);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    response.headers.set(name, value);
  }
  return response;
}

/** Matches the path the router will serve: "/%6Aobs" is "/jobs". */
function decodePath(pathname: string): string {
  try {
    return decodeURIComponent(pathname);
  } catch {
    return pathname;
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|api/|favicon.ico|robots.txt).*)"],
};
