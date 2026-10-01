import { expect, test } from "@playwright/test";
import { formAlert, RECRUITER, seedPassword, signIn, uniqueEmail } from "./support";

test("a recruiter signs in, comes back to the page they wanted, and signs out", async ({
  page,
}) => {
  await page.goto("/jobs?status=open");
  await expect(page).toHaveURL(/\/login\?next=/);
  await signIn(page, RECRUITER, seedPassword());
  await expect(page).toHaveURL(/\/jobs\?status=open$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Jobs");

  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/jobs");
  await expect(page).toHaveURL(/\/login\?next=/);
});

test("a wrong password is refused without saying which part was wrong", async ({ page }) => {
  await page.goto("/login");
  await signIn(page, RECRUITER, "not the right password at all");
  await expect(formAlert(page)).toHaveText("Email or password is incorrect.");
});

test("repeated failures ask the visitor to wait", async ({ page }) => {
  // Lockout treats unknown emails like real ones, so no real account is locked here.
  const email = uniqueEmail("nobody");
  await page.goto("/login");
  for (let attempt = 0; attempt < 5; attempt++) {
    await signIn(page, email, "a guess that will never be right");
    await expect(formAlert(page)).toBeVisible();
  }
  await expect(formAlert(page)).toHaveText("Too many attempts. Try again in 1 minute.");
});

test("a state change without the CSRF token is refused", async ({ page }) => {
  await page.goto("/login");
  await signIn(page, RECRUITER, seedPassword());
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
  const status = await page.evaluate(() =>
    fetch("/api/v1/auth/sessions/revoke-others", { method: "POST" }).then((r) => r.status),
  );
  expect(status).toBe(403);
});
