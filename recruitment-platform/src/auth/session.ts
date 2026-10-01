import { z } from "@/config/zod";
import { devToolsEnabled } from "../config/environment";
import { DEV_SESSIONS } from "./dev-sessions";
import { isPermission, isRole, type Session } from "./permissions";

/**
 * Resolves the signed-in session from a request's cookies. Kept free of Next's request APIs so
 * the proxy, server components and tests share it.
 */

export const DEV_ROLE_COOKIE = "hv_dev_role";
/** The proxy forwards the requested path and query to the pages under this header. */
export const PATH_HEADER = "x-hv-path";

const DEFAULT_API = "http://127.0.0.1:8000";
const TIMEOUT_MS = 2_000;

type Env = Record<string, string | undefined>;

const sessionSchema = z.object({
  user: z.object({ id: z.string(), name: z.string(), email: z.string() }),
  organization: z.object({ id: z.string(), name: z.string() }).nullable(),
  roles: z.array(z.string()),
  // A permission this build doesn't know grants nothing, so it is dropped rather than refused.
  permissions: z.array(z.string()).transform((list) => list.filter(isPermission)),
});

export async function resolveSession(
  cookies: Readonly<Record<string, string>>,
  env: Env,
  fetcher: typeof fetch = fetch,
): Promise<Session | null> {
  const devRole = cookies[DEV_ROLE_COOKIE];
  if (devToolsEnabled(env) && isRole(devRole)) return DEV_SESSIONS[devRole];

  const header = Object.entries(cookies)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  if (!header) return null;

  // SP-02 serves this endpoint. Until then, and whenever the API is down, nobody is signed in.
  try {
    const response = await fetcher(
      `${env.HV_API_INTERNAL_URL ?? DEFAULT_API}/api/v1/auth/session`,
      {
        headers: { cookie: header, accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(TIMEOUT_MS),
      },
    );
    if (!response.ok) return null;
    const parsed = sessionSchema.safeParse(await response.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}
