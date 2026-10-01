import { type ManifestRoute, ROUTES, type RoutePath, routeFor } from "@/auth/manifest";
import { can, type Session } from "@/auth/permissions";

/** What the shell shows a session: its sidebar, its palette, the trail to the current page. */

/** `g` then a letter (master plan §6.2: keyboard navigation). */
export const SHORTCUTS = {
  d: "/dashboard",
  j: "/jobs",
  c: "/candidates",
  i: "/interviews",
  q: "/questions",
  r: "/reports",
} as const satisfies Record<string, RoutePath>;

export function navRoutes(session: Session): ManifestRoute[] {
  return ROUTES.filter((route) => route.nav && can(session, route.permission));
}

export function permittedRoutes(session: Session): ManifestRoute[] {
  return ROUTES.filter((route) => can(session, route.permission));
}

export function isActive(pathname: string, path: string): boolean {
  return pathname === path || pathname.startsWith(`${path}/`);
}

/** The section's own page, then the page itself when it is a different one. */
export function breadcrumbTrail(pathname: string): ManifestRoute[] {
  const route = routeFor(pathname);
  if (!route) return [];
  const root = ROUTES.find((entry) => entry.nav && entry.section === route.section);
  return root && root !== route ? [root, route] : [route];
}

export function shortcutFor(path: string): string | undefined {
  return Object.entries(SHORTCUTS).find(([, target]) => target === path)?.[0];
}
