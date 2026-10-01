import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { type RoutePath, routeAt } from "./manifest";
import { loginPath } from "./next-path";
import { can, type Session } from "./permissions";
import { PATH_HEADER, resolveSession } from "./session";

/**
 * Session checks for server components and server actions. These are the authority: the proxy
 * only answers early, and a layout isn't re-rendered when moving between its pages.
 */

export const getSession = cache(async (): Promise<Session | null> => {
  const jar = await cookies();
  const values = Object.fromEntries(jar.getAll().map((cookie) => [cookie.name, cookie.value]));
  return resolveSession(values, process.env);
});

/** The session, or a redirect to sign in that returns here afterwards. */
export async function requireSession(): Promise<Session> {
  const session = await getSession();
  if (!session) redirect(loginPath((await headers()).get(PATH_HEADER)));
  return session;
}

/** The session when it may open the route; null when it may not (render <Forbidden />). */
export async function requireRoute(path: RoutePath): Promise<Session | null> {
  const session = await requireSession();
  return can(session, routeAt(path).permission) ? session : null;
}
