import { expect, test } from "@playwright/test";
import { DEV_SESSIONS } from "../src/auth/dev-sessions";
import { ROUTES } from "../src/auth/manifest";
import { can, ROLES } from "../src/auth/permissions";
import { messages, samplePath, signInAs } from "./support";

// Every IA route for every role (SP-03 exit criterion): it renders, or is refused with 403.
for (const role of ROLES) {
  test.describe(`as ${role}`, () => {
    test.beforeEach(async ({ context }) => {
      await signInAs(context, role);
    });

    for (const route of ROUTES) {
      const allowed = can(DEV_SESSIONS[role], route.permission);
      test(`${route.path} is ${allowed ? "shown" : "refused"}`, async ({ page }) => {
        const response = await page.goto(samplePath(route.path));
        const heading = page.getByRole("heading", { level: 1 });
        if (allowed) {
          expect(response?.status()).toBe(200);
          await expect(heading).toHaveText(messages.routes[route.titleKey]);
        } else {
          expect(response?.status()).toBe(403);
          await expect(heading).toHaveText(messages.forbidden.title);
        }
      });
    }
  });
}

test("an anonymous visitor is sent to sign in, and comes back afterwards", async ({ page }) => {
  await page.goto("/jobs?status=open");
  await expect(page).toHaveURL(/\/login\?next=%2Fjobs%3Fstatus%3Dopen$/);
  await page.getByRole("button", { name: "Continue as Recruiter" }).click();
  await expect(page).toHaveURL(/\/jobs\?status=open$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Jobs");
});
