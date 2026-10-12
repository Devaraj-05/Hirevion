import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { type Browser, expect, type Page, test } from "@playwright/test";
import { RECRUITER, seedPassword, signedIn } from "./support";

// The candidate portal against the real API (SP-07b exit criterion): the invitation email in
// Mailpit → set a password → the interview is listed; a reschedule request reaches the recruiter.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const PORTAL = "http://candidate.hirevion.localhost:3100";
const MAILPIT = process.env.HV_MAILPIT_URL ?? "http://127.0.0.1:8025";
// The mock AI's scripted parse (e2e/auth/ai-scripts.json) reads this resume as Meera Iyer.
const CANDIDATE = "Meera Iyer";
const EMAIL = "meera.iyer@example.test";
const RESUME = [
  "Meera Iyer",
  "meera.iyer@example.test | +91 98450 12345 | Chennai",
  "",
  "Skills",
  "Python, PostgreSQL",
  "",
  "Experience",
  "Data Engineer, Globex Analytics (2021 - present)",
  "",
].join("\n");

async function noAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

/** The text of the invitation for `job` (Meera is invited to other jobs by other tests too). */
async function invitation(job: string): Promise<string> {
  for (let attempt = 0; attempt < 75; attempt++) {
    const search = await fetch(
      `${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${EMAIL}" subject:"${job}"`)}`,
    ).then((response) => response.json() as Promise<{ messages: { ID: string }[] }>);
    const first = search.messages[0];
    if (first) {
      const body = await fetch(`${MAILPIT}/api/v1/message/${first.ID}`).then(
        (response) => response.json() as Promise<{ Text: string }>,
      );
      return body.Text;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`no invitation for ${job}`);
}

/** As a recruiter: an open job with Meera shortlisted, and her interview created and sent. */
async function inviteMeera(page: Page, suffix: string): Promise<string> {
  const job = `E2E Portal Engineer ${suffix}`;
  const template = `E2E portal interview ${suffix}`;
  await page.goto("/interviews/templates/new");
  await page.getByLabel("Name").fill(template);
  await page.getByLabel("Skill 1", { exact: true }).fill("Python");
  await page.getByRole("button", { name: "Create template" }).click();
  await expect(page.getByRole("heading", { level: 1, name: template })).toBeVisible({
    timeout: 15_000,
  });
  await page.goto("/jobs/new");
  await page.getByLabel("Title").fill(job);
  await page.getByLabel("Description", { exact: true }).fill("Builds the candidate portal.");
  await page.getByLabel("Add a skill").fill("Python");
  await page.getByLabel("Add a skill").press("Enter");
  await page.getByRole("button", { name: "Create job" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("E2E Portal Engineer");
  await page.getByRole("button", { name: "Open job" }).click();
  await expect(page.getByText("The job is now Open.")).toBeVisible();
  await page.getByRole("tab", { name: "Resumes" }).click();
  await page.getByLabel("Choose files").setInputFiles({
    name: "meera-iyer.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(RESUME),
  });
  await expect(page.getByRole("link", { name: CANDIDATE })).toBeVisible({ timeout: 90_000 });
  await page.getByRole("tab", { name: "Ranking" }).click();
  await page.getByRole("button", { name: "Screen candidates" }).click();
  await expect(page.getByText("1 of 1 screened")).toBeVisible({ timeout: 60_000 });
  await page.getByLabel(`Select ${CANDIDATE}`).check();
  await page.getByRole("button", { name: "Shortlist" }).click();
  await expect(page.getByText("1 candidate updated.")).toBeVisible();
  await page.getByLabel(`Select ${CANDIDATE}`).check();
  await page.getByRole("button", { name: "Create interview" }).click();
  const dialog = page.getByRole("dialog", { name: "Create an interview" });
  await dialog.getByLabel("Template").selectOption({ label: `${template} (45 min)` });
  await dialog.getByRole("button", { name: "Create and invite" }).click();
  await expect(page.getByText("Interview created")).toBeVisible();
  return job;
}

interface MailSummary {
  ID: string;
}

async function newestReset(): Promise<MailSummary | undefined> {
  const query = `to:"${EMAIL}" subject:"Reset your Hirevion password"`;
  const search = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(query)}`).then(
    (response) => response.json() as Promise<{ messages: MailSummary[] }>,
  );
  return search.messages[0];
}

/** Asks the portal for a link and returns the path of the one that arrives. */
async function resetLink(page: Page): Promise<string> {
  const before = (await newestReset())?.ID;
  await page.goto(`${PORTAL}/forgot-password`);
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByRole("status")).toBeVisible();
  for (let attempt = 0; attempt < 75; attempt++) {
    const newest = await newestReset();
    if (newest && newest.ID !== before) {
      const body = await fetch(`${MAILPIT}/api/v1/message/${newest.ID}`).then(
        (response) => response.json() as Promise<{ Text: string }>,
      );
      const path = body.Text.match(/\/(?:reset-password|invitation)\/[\w-]+/)?.[0];
      if (path) return path;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("no reset link arrived");
}

/** Sets a password from an emailed link; false when the link was already spent. */
async function setPassword(page: Page, path: string, password: string): Promise<boolean> {
  await page.goto(`${PORTAL}${path}`);
  await page.getByLabel("New password", { exact: true }).fill(password);
  await page.getByLabel("Confirm the new password").fill(password);
  await page.getByRole("button", { name: /Set the password|Save the new password/ }).click();
  const signIn = page.getByRole("heading", { level: 1, name: "Sign in to the candidate portal" });
  const expired = page.getByText("This link has expired or was already used.");
  await expect(signIn.or(expired)).toBeVisible({ timeout: 15_000 });
  return signIn.isVisible();
}

/** Meera's portal: the invitation's link when her account is new; once an earlier run (or the
 * interviews test) has activated it, the invitation says sign in, so she resets instead. */
async function candidatePortal(browser: Browser, job: string, password: string): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  const text = await invitation(job);
  const link = text.match(/\/invitation\/[\w-]+/)?.[0];
  if (!link || !(await setPassword(page, link, password))) {
    expect(await setPassword(page, await resetLink(page), password)).toBe(true);
  }
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Your interviews" })).toBeVisible();
  return page;
}

test("a candidate sets a password from the invitation, sees the interview and asks to reschedule", async ({
  page,
  browser,
}) => {
  test.setTimeout(240_000);
  const suffix = randomUUID().slice(0, 6);
  await signedIn(page, RECRUITER, seedPassword());
  const job = await inviteMeera(page, suffix);

  const candidate = await candidatePortal(browser, job, `portal passphrase ${suffix}`);
  const card = candidate.getByRole("listitem").filter({ hasText: job });
  await expect(card.getByText("Invited")).toBeVisible();
  await expect(card.getByText(/Opens in|Closes in/)).toBeVisible();
  await noAxeViolations(candidate);

  // The recruiter app's API isn't reachable from the portal's host.
  expect((await candidate.request.get(`${PORTAL}/api/v1/auth/session`)).status()).toBe(404);

  await card.getByRole("link", { name: "Ask to reschedule" }).click();
  await expect(candidate.getByLabel("What do you need?")).toHaveValue("reschedule");
  await candidate.getByLabel("When would suit you?").fill("Any weekday after the 20th");
  await candidate.getByLabel("Details").fill(`Travelling that week (${suffix})`);
  await candidate.getByRole("button", { name: "Send the request" }).click();
  await expect(candidate.getByRole("status")).toContainText("Request sent.");
  await expect(candidate.getByText(`Travelling that week (${suffix})`)).toBeVisible();
  await noAxeViolations(candidate);

  // The recruiter finds it and answers it.
  await page.goto("/candidates/requests");
  await page.getByLabel("Status").selectOption("open");
  const row = page.getByRole("row").filter({ hasText: CANDIDATE }).first();
  await expect(row.getByText("Reschedule an interview")).toBeVisible();
  await row.getByRole("button", { name: /^Update RQ-/ }).click();
  const dialog = page.getByRole("dialog", { name: "Update the request" });
  await expect(dialog.getByText(`Travelling that week (${suffix})`)).toBeVisible();
  await expect(dialog.getByText("Any weekday after the 20th")).toBeVisible();
  await noAxeViolations(page);
  await dialog.getByLabel("New status").selectOption("resolved");
  await dialog.getByLabel("Reply to the candidate").fill(`Moved to the 22nd (${suffix})`);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Request updated.")).toBeVisible();

  await candidate.reload();
  await expect(candidate.getByText(`Moved to the 22nd (${suffix})`)).toBeVisible();
});
