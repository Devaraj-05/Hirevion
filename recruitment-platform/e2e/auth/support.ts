import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  type Browser,
  type BrowserContext,
  expect,
  type Locator,
  type Page,
} from "@playwright/test";

/** Helpers for the sign-in suite, which runs against the real API, database and Mailpit. */

const REPO = fileURLToPath(new URL("../../../", import.meta.url));
const MAILPIT = process.env.HV_MAILPIT_URL ?? "http://127.0.0.1:8025";

function fromDotEnv(name: string): string | undefined {
  try {
    const line = readFileSync(`${REPO}.env`, "utf8")
      .split(/\r?\n/)
      .find((entry) => entry.startsWith(`${name}=`));
    return line?.slice(name.length + 1).replace(/^"|"$/g, "");
  } catch {
    return undefined;
  }
}

/** The seeded users' password (`hv seed-identity`). */
export function seedPassword(): string {
  const value = process.env.HV_SEED_PASSWORD ?? fromDotEnv("HV_SEED_PASSWORD");
  if (!value) throw new Error("Set HV_SEED_PASSWORD (it is in .env) for the sign-in suite");
  return value;
}

export const RECRUITER = "recruiter@acme.example.test";

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${randomUUID().slice(0, 8)}@hirevion.example.test`;
}

/** Invites a super admin through `hv create-super-admin`; returns the set-password path. */
export function inviteSuperAdmin(email: string): string {
  const uv = process.env.HV_UV ?? "uv";
  const output = execFileSync(
    uv,
    ["run", "hv", "create-super-admin", "--email", email, "--name", "E2E Admin"],
    { cwd: REPO, encoding: "utf8" },
  );
  const path = output.match(/\/set-password\/[\w-]+/)?.[0];
  if (!path) throw new Error(`no set-password link in: ${output}`);
  return path;
}

/** The path of the newest emailed link to `to` that starts with `segment` (then a token). */
export async function emailedLink(to: string, segment: string): Promise<string> {
  for (let attempt = 0; attempt < 50; attempt++) {
    const search = await fetch(
      `${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`,
    ).then((response) => response.json() as Promise<{ messages: { ID: string }[] }>);
    for (const message of search.messages) {
      const body = await fetch(`${MAILPIT}/api/v1/message/${message.ID}`).then(
        (response) => response.json() as Promise<{ Text: string }>,
      );
      // Tokens are URL-safe base64, so the match ends where the token does.
      const path = body.Text.match(new RegExp(`${segment}[\\w-]+`))?.[0];
      if (path) return path;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`no ${segment} email reached ${to}`);
}

/** The page's own alert (Next's route announcer is also role="alert"). */
export function formAlert(page: Page): Locator {
  return page.locator('[role="alert"]:not(#__next-route-announcer__)');
}

export async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** A fresh super admin with a password, signed in; returns their credentials. */
export async function newSignedInAdmin(page: Page): Promise<{ email: string; password: string }> {
  const email = uniqueEmail("admin");
  const password = `first password for ${randomUUID().slice(0, 8)}`;
  await page.goto(inviteSuperAdmin(email));
  await page.getByLabel("New password", { exact: true }).fill(password);
  await page.getByLabel("Confirm the new password").fill(password);
  await page.getByRole("button", { name: "Set the password" }).click();
  await expect(page).toHaveURL(/\/login\?set=1$/);
  await signIn(page, email, password);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
  return { email, password };
}

export const ORG_ADMIN = "org-admin@acme.example.test";
export const SUPER_ADMIN = "super@hirevion.example.test";

/** Answers the step-up dialog that the first sensitive change of a session opens. */
export async function confirmPassword(page: Page, password: string): Promise<void> {
  const dialog = page.getByRole("dialog", { name: "Confirm your password" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Password").fill(password);
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(dialog).toBeHidden();
}

/** Signs in on a fresh page at /login and waits for the dashboard. */
export async function signedIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await signIn(page, email, password);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
}

/** The invitee, in their own browser: sets a password from the emailed link and signs in. */
export async function acceptInvitation(
  browser: Browser,
  email: string,
  landsOn = "Dashboard",
): Promise<{ page: Page; context: BrowserContext; password: string }> {
  const context = await browser.newContext();
  const page = await context.newPage();
  const password = `invited password ${randomUUID().slice(0, 8)}`;
  await page.goto(await emailedLink(email, "/set-password/"));
  await page.getByLabel("New password", { exact: true }).fill(password);
  await page.getByLabel("Confirm the new password").fill(password);
  await page.getByRole("button", { name: "Set the password" }).click();
  await expect(page).toHaveURL(/\/login\?set=1$/);
  await signIn(page, email, password);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(landsOn);
  return { page, context, password };
}
