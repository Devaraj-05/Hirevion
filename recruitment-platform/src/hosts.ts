/**
 * One app, two hosts (ADR-0012): the recruiter app and the candidate portal. `proxy.ts` rewrites
 * each host's paths onto its own route tree (`app/recruiter`, `app/portal`), so a host can only
 * ever reach its own pages.
 */

export type HostKind = "recruiter" | "portal" | "unknown";
export type ServedHost = Exclude<HostKind, "unknown">;

export interface HostConfig {
  recruiter: readonly string[];
  portal: readonly string[];
}

type Env = Record<string, string | undefined>;

const DEFAULT_RECRUITER_HOSTS = "app.hirevion.localhost,localhost,127.0.0.1,::1";
const DEFAULT_PORTAL_HOSTS = "candidate.hirevion.localhost";
const PREFIX: Record<ServedHost, string> = { recruiter: "/recruiter", portal: "/portal" };

function list(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

export function hostConfig(env: Env = process.env): HostConfig {
  return {
    recruiter: list(env.HV_WEB_RECRUITER_HOSTS ?? DEFAULT_RECRUITER_HOSTS),
    portal: list(env.HV_WEB_PORTAL_HOSTS ?? DEFAULT_PORTAL_HOSTS),
  };
}

function hostname(host: string): string {
  const value = host.trim().toLowerCase();
  if (value.startsWith("[")) {
    return value.slice(1, value.indexOf("]"));
  }
  const colon = value.lastIndexOf(":");
  return colon > -1 && value.indexOf(":") === colon ? value.slice(0, colon) : value;
}

export function hostKind(host: string | null, config: HostConfig): HostKind {
  if (!host) return "unknown";
  const name = hostname(host);
  if (config.portal.includes(name)) return "portal";
  if (config.recruiter.includes(name)) return "recruiter";
  return "unknown";
}

/** The internal route for a public path on `kind`'s host. */
export function internalPath(kind: ServedHost, pathname: string): string {
  return pathname === "/" ? PREFIX[kind] : `${PREFIX[kind]}${pathname}`;
}
