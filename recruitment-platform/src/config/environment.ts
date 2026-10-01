/**
 * Development tools (fixture sessions, the component gallery) exist until SP-02 brings real
 * sign-in. They must never reach production, so the app refuses to build or start with both set.
 */

type Env = Record<string, string | undefined>;

/** On when HV_WEB_DEV_TOOLS=true, and by default under `next dev`; HV_WEB_DEV_TOOLS=false wins. */
export function devToolsEnabled(env: Env = process.env): boolean {
  const flag = env.HV_WEB_DEV_TOOLS;
  return flag === undefined ? env.NODE_ENV === "development" : flag === "true";
}

export function assertSafeEnvironment(env: Env = process.env): void {
  if (devToolsEnabled(env) && env.HV_ENVIRONMENT === "production") {
    throw new Error("HV_WEB_DEV_TOOLS must never be enabled when HV_ENVIRONMENT is production.");
  }
}
