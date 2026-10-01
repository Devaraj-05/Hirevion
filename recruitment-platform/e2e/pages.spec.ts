import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { ROUTES } from "../src/auth/manifest";
import { PORTAL_PAGES } from "../src/portal/pages";
import { APP, PORTAL, signInAs, watchForProblems } from "./support";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const PAGES = [
  ...ROUTES.map((route) => `${APP}${route.path}`),
  `${APP}/login`,
  `${APP}/forbidden`,
  `${APP}/dev/ui`,
  ...PORTAL_PAGES.map((page) => `${PORTAL}${page.path.replace("[token]", "e2e-token")}`),
];

// Every page, as the super admin (who may open them all), in both themes: no WCAG 2.2 AA
// violations, no CSP violations and no console errors (hydration errors land there too).
for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ context, page }) => {
      await signInAs(context, "super_admin");
      await page.addInitScript((value) => localStorage.setItem("hv_theme", value), theme);
    });

    for (const url of PAGES) {
      test(new URL(url).host.split(".")[0] + new URL(url).pathname, async ({ page }) => {
        const problems = await watchForProblems(page);
        await page.goto(url);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
        const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
        expect(results.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual(
          [],
        );
        expect(await problems()).toEqual([]);
      });
    }
  });
}
