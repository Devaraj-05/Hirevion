import { expect, test } from "@playwright/test";
import { emailedLink, formAlert, newSignedInAdmin, signIn, uniqueEmail } from "./support";

// Each test changes its own fresh account (invited with `hv create-super-admin`, first password
// set through the emailed-link page), so the seeded users stay as they are.

test("a forgotten password is reset from the emailed link", async ({ page, context }) => {
  const { email, password } = await newSignedInAdmin(page);
  await context.clearCookies();

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByRole("status")).toContainText(`If an account exists for ${email}`);

  await page.goto(await emailedLink(email, "/reset-password/"));
  await page.getByLabel("New password", { exact: true }).fill("too short pass");
  await page.getByLabel("Confirm the new password").fill("too short pass");
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page.getByText("Use at least 15 characters.")).toBeVisible();

  const next = `${password} then changed`;
  await page.getByLabel("New password", { exact: true }).fill(next);
  await page.getByLabel("Confirm the new password").fill(next);
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page).toHaveURL(/\/login\?reset=1$/);

  await signIn(page, email, password);
  await expect(formAlert(page)).toHaveText("Email or password is incorrect.");
  await signIn(page, email, next);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
});

test("an email address is changed once the new one is confirmed", async ({ page }) => {
  const { password } = await newSignedInAdmin(page);
  const replacement = uniqueEmail("moved");

  await page.goto("/account");
  await page.getByLabel("New email address").fill(replacement);
  await page.getByLabel("Your password").fill(password);
  await page.getByRole("button", { name: "Send a confirmation link" }).click();
  await expect(page.getByRole("status")).toContainText(`Check ${replacement}`);

  await page.goto(await emailedLink(replacement, "/verify-email/"));
  await page.getByRole("button", { name: "Confirm my new email address" }).click();
  await expect(page.getByRole("status")).toContainText("Your email address is confirmed");

  await page.goto("/account");
  await expect(page.getByText(`You sign in with ${replacement}.`)).toBeVisible();
});

test("signing out everywhere else ends the other browser's session", async ({ page, browser }) => {
  const { email, password } = await newSignedInAdmin(page);
  const other = await browser.newContext();
  const elsewhere = await other.newPage();
  await elsewhere.goto("/login");
  await signIn(elsewhere, email, password);
  await expect(elsewhere.getByRole("heading", { level: 1 })).toHaveText("Dashboard");

  await page.goto("/account");
  await expect(page.getByText("This device")).toBeVisible();
  await page.getByRole("button", { name: "Sign out everywhere else" }).click();
  await expect(page.getByRole("button", { name: /^Sign out .+ on .+$/ })).toHaveCount(0);

  await elsewhere.goto("/jobs");
  await expect(elsewhere).toHaveURL(/\/login\?next=%2Fjobs$/);
  await other.close();
});
