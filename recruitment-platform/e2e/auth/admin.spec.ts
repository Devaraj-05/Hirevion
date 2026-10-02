import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import {
  acceptInvitation,
  confirmPassword,
  formAlert,
  ORG_ADMIN,
  SUPER_ADMIN,
  seedPassword,
  signedIn,
  signIn,
  uniqueEmail,
} from "./support";

// Organisations and access against the real API (SP-02b). Every account a test changes is a
// fresh one it invites, so the seeded users stay as they are.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function noAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

/** Invites someone from /admin/users with one role; the first change of a session steps up. */
async function invite(
  page: Page,
  email: string,
  role: string,
  { stepUp }: { stepUp: boolean },
): Promise<string> {
  // Named after the address, so each invitee is unique however many runs the database has seen.
  const name = `E2E ${email.split("@")[0]}`;
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Invite user" }).click();
  const dialog = page.getByRole("dialog", { name: "Invite a user" });
  await dialog.getByLabel("Email", { exact: true }).fill(email);
  await dialog.getByLabel("Name", { exact: true }).fill(name);
  await dialog.getByRole("checkbox", { name: role, exact: true }).click();
  await dialog.getByRole("button", { name: "Send invitation" }).click();
  if (stepUp) await confirmPassword(page, seedPassword());
  await expect(dialog).toBeHidden();
  return name;
}

const nav = (page: Page) => page.getByRole("navigation", { name: "Main" });

test("an organisation admin invites a recruiter, who joins and sees only their pages", async ({
  page,
  browser,
}) => {
  await signedIn(page, ORG_ADMIN, seedPassword());
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Invite user" }).click();
  await expect(page.getByRole("dialog", { name: "Invite a user" })).toBeVisible();
  await noAxeViolations(page);
  await page.keyboard.press("Escape");

  const email = uniqueEmail("recruiter");
  await invite(page, email, "Recruiter", { stepUp: true });

  const invitee = await acceptInvitation(browser, email);
  await expect(nav(invitee.page).getByRole("link", { name: "Jobs" })).toBeVisible();
  await expect(nav(invitee.page).getByRole("link", { name: "Administration" })).toHaveCount(0);
  await invitee.context.close();
});

test("a custom role's permissions apply at once, without signing in again", async ({
  page,
  browser,
}) => {
  const roleName = `Talent sourcer ${Date.now().toString(36)}`;
  await signedIn(page, ORG_ADMIN, seedPassword());
  await page.goto("/admin/roles");
  await page.getByRole("button", { name: "New role" }).click();
  const editor = page.getByRole("dialog", { name: "New role" });
  await noAxeViolations(page);
  await editor.getByLabel("Name").fill(roleName);
  await editor.getByRole("checkbox", { name: "View jobs" }).click();
  await editor.getByRole("checkbox", { name: "Manage teams" }).click();
  await editor.getByRole("button", { name: "Save role" }).click();
  await confirmPassword(page, seedPassword());
  await expect(editor).toBeHidden();

  const email = uniqueEmail("sourcer");
  await invite(page, email, roleName, { stepUp: false });
  // The role leaves out the dashboard, so they start on the first page it opens.
  const sourcer = await acceptInvitation(browser, email, "Jobs");
  await sourcer.page.goto("/admin/teams");
  await expect(sourcer.page.getByRole("heading", { level: 1 })).toHaveText("Teams");
  await sourcer.page.goto("/admin/users");
  await expect(sourcer.page.getByText("You don't have access to this page")).toBeVisible();

  await page.goto("/admin/roles");
  await page.getByRole("button", { name: `Edit ${roleName}` }).click();
  const again = page.getByRole("dialog", { name: `Edit ${roleName}` });
  await again.getByRole("checkbox", { name: "Manage teams" }).click();
  await again.getByRole("button", { name: "Save role" }).click();
  await expect(again).toBeHidden();

  await sourcer.page.goto("/admin/teams");
  await expect(sourcer.page.getByText("You don't have access to this page")).toBeVisible();
  await sourcer.context.close();
});

test("disabling someone ends the session they have open", async ({ page, browser }) => {
  await signedIn(page, ORG_ADMIN, seedPassword());
  const email = uniqueEmail("leaver");
  const name = await invite(page, email, "Recruiter", { stepUp: true });
  const leaver = await acceptInvitation(browser, email);

  await page.goto("/admin/users");
  await page.getByRole("searchbox", { name: "Search by name or email" }).fill(email);
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: `Open ${name}` }).click();
  const sheet = page.getByRole("dialog", { name });
  await sheet.getByRole("button", { name: "Disable user" }).click();
  await expect(sheet.getByText("Disabled: can't sign in.")).toBeVisible();

  await leaver.page.goto("/jobs");
  await expect(leaver.page).toHaveURL(/\/login\?next=%2Fjobs$/);
  await leaver.context.close();
});

test("a super admin creates an organisation, then suspends and reactivates it", async ({
  page,
  browser,
}) => {
  const suffix = Date.now().toString(36);
  const name = `E2E Org ${suffix}`;
  const adminEmail = uniqueEmail("first-admin");
  await signedIn(page, SUPER_ADMIN, seedPassword());
  await page.goto("/platform/organizations");
  await page.getByRole("button", { name: "New organisation" }).click();
  const dialog = page.getByRole("dialog", { name: "New organisation" });
  await dialog.getByLabel("Name", { exact: true }).fill(name);
  await expect(dialog.getByLabel("Short name")).toHaveValue(`e2e-org-${suffix}`);
  await dialog.getByLabel("First admin's name").fill("First Admin");
  await dialog.getByLabel("First admin's email").fill(adminEmail);
  await dialog.getByRole("button", { name: "Create" }).click();
  await confirmPassword(page, seedPassword());
  await expect(dialog).toBeHidden();

  const firstAdmin = await acceptInvitation(browser, adminEmail);
  await expect(nav(firstAdmin.page).getByRole("link", { name: "Administration" })).toBeVisible();

  await page.getByRole("searchbox", { name: "Search by name or short name" }).fill(suffix);
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: `Actions for ${name}` }).click();
  await page.getByRole("menuitem", { name: "Suspend" }).click();
  const suspend = page.getByRole("dialog", { name: `Suspend ${name}` });
  await suspend.getByLabel("Reason").fill("End-to-end check");
  await suspend.getByRole("button", { name: "Suspend" }).click();
  await expect(suspend).toBeHidden();

  await firstAdmin.page.goto("/jobs");
  await expect(firstAdmin.page).toHaveURL(/\/login\?next=%2Fjobs$/);
  await signIn(firstAdmin.page, adminEmail, firstAdmin.password);
  await expect(formAlert(firstAdmin.page)).toHaveText("Email or password is incorrect.");

  await page.getByRole("button", { name: `Actions for ${name}` }).click();
  await page.getByRole("menuitem", { name: "Reactivate" }).click();
  await expect(page.getByRole("row", { name: new RegExp(name) })).toContainText("Active");
  await signIn(firstAdmin.page, adminEmail, firstAdmin.password);
  await expect(firstAdmin.page.getByRole("heading", { level: 1 })).toHaveText("Jobs");
  await firstAdmin.context.close();
});
