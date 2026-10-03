import type { BrowserContext, Page } from "@playwright/test";
import messages from "../messages/en-IN.json" with { type: "json" };
import type { Role } from "../src/auth/permissions";

export const APP = "http://app.hirevion.localhost:3100";
export const PORTAL = "http://candidate.hirevion.localhost:3100";
export { messages };

/** Signs in with the development role switcher's cookie. */
export async function signInAs(context: BrowserContext, role: Role): Promise<void> {
  await context.addCookies([{ name: "hv_dev_role", value: role, url: APP }]);
}

/** Records CSP violations and console errors (including React hydration errors) from page load. */
export async function watchForProblems(page: Page): Promise<() => Promise<string[]>> {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
  await page.addInitScript(() => {
    const violations: string[] = [];
    (window as unknown as { __cspViolations: string[] }).__cspViolations = violations;
    document.addEventListener("securitypolicyviolation", (event) => {
      violations.push(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  return async () => {
    const csp = await page.evaluate(
      () => (window as unknown as { __cspViolations?: string[] }).__cspViolations ?? [],
    );
    return [...problems, ...csp.map((violation) => `csp: ${violation}`)];
  };
}

/** A manifest path with a sample id in its dynamic segment ("/jobs/[id]" -> "/jobs/<uuid>"). */
export function samplePath(path: string): string {
  return path.replace("[id]", "0190f1a2-0000-7000-8000-000000000000");
}
