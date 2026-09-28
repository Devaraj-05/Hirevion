export type Route = "home" | "media" | "livekit";

export interface ParsedRoute {
  route: Route;
  params: URLSearchParams;
}

const ROUTES: readonly string[] = ["home", "media", "livekit"];

function isRoute(value: string): value is Route {
  return ROUTES.includes(value);
}

/** Parses a location hash such as `#/media?auto=60`; unknown paths map to `home`. */
export function parseRoute(hash: string): ParsedRoute {
  const body = hash.replace(/^#\/?/, "");
  const queryStart = body.indexOf("?");
  const path = queryStart === -1 ? body : body.slice(0, queryStart);
  const query = queryStart === -1 ? "" : body.slice(queryStart + 1);
  return { route: isRoute(path) ? path : "home", params: new URLSearchParams(query) };
}
