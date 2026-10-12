import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { RECRUITER, seedPassword, signedIn } from "./support";

// Interviews against the real API (SP-07a): shortlist a screened candidate, create their
// interview from the ranking, and find the invitation, with all eight PRD §25 contents, in Mailpit.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
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
const MAILPIT = process.env.HV_MAILPIT_URL ?? "http://127.0.0.1:8025";

async function noAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

/** The invitation for this run's job (earlier runs invited the same candidate to others). */
async function invitationText(to: string, job: string): Promise<string> {
  for (let attempt = 0; attempt < 75; attempt++) {
    const search = await fetch(
      `${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}" subject:"${job}"`)}`,
    ).then((response) => response.json() as Promise<{ messages: { ID: string }[] }>);
    const first = search.messages[0];
    if (first) {
      const body = await fetch(`${MAILPIT}/api/v1/message/${first.ID}`).then(
        (response) => response.json() as Promise<{ Text: string }>,
      );
      return body.Text.replace(/\s+/g, " ");
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`no invitation reached ${to}`);
}

test("a recruiter invites a shortlisted candidate to an interview", async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = randomUUID().slice(0, 6);
  const job = `E2E Platform Engineer ${suffix}`;
  await signedIn(page, RECRUITER, seedPassword());

  // A template for the interview.
  const template = `E2E interview ${suffix}`;
  await page.goto("/interviews/templates/new");
  await page.getByLabel("Name").fill(template);
  await page.getByLabel("Skill 1", { exact: true }).fill("Python");
  await page.getByRole("button", { name: "Create template" }).click();
  await expect(page.getByRole("heading", { level: 1, name: template })).toBeVisible({
    timeout: 15_000,
  });

  // A job with one screened, shortlisted candidate.
  await page.goto("/jobs/new");
  await page.getByLabel("Title").fill(job);
  await page
    .getByLabel("Description", { exact: true })
    .fill("Builds the platform's data services.");
  await page.getByLabel("Add a skill").fill("Python");
  await page.getByLabel("Add a skill").press("Enter");
  await page.getByRole("button", { name: "Create job" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("E2E Platform Engineer");
  // Interviews are for open jobs only.
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

  // Create the interview from the ranking.
  await page.getByLabel(`Select ${CANDIDATE}`).check();
  await page.getByRole("button", { name: "Create interview" }).click();
  const dialog = page.getByRole("dialog", { name: "Create an interview" });
  await dialog.getByLabel("Template").selectOption({ label: `${template} (45 min)` });
  await noAxeViolations(page);
  await dialog.getByRole("button", { name: "Create and invite" }).click();
  await expect(page.getByText("Interview created")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Interview", exact: true })).toBeVisible();

  // It's upcoming, and its page shows the pinned template and the invitation.
  await page.goto("/interviews");
  const search = page.getByRole("searchbox", { name: "Search by candidate, job or IV number" });
  await search.fill(job);
  await search.press("Enter");
  const open = page.getByRole("link", { name: `Open the interview with ${CANDIDATE}` });
  await expect(open).toHaveCount(1);
  await open.click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(CANDIDATE);
  await expect(page.getByText(`${template}, version 1`)).toBeVisible();
  await expect(page.getByText("Invited", { exact: true }).first()).toBeVisible();
  await noAxeViolations(page);

  // The invitation, in Mailpit, with §25's eight contents and the set-password link.
  const text = await invitationText(EMAIL, job);
  for (const expected of [
    "invites you to an AI interview",
    `Role: ${job}`,
    "Duration: 45 minutes",
    "Window:",
    "/download",
    "System requirements",
    "Privacy and recording",
    "Support",
  ]) {
    expect(text).toContain(expected);
  }
  // A new account gets the set-password link; once the portal test has activated Meera's
  // account (SP-07b), the invitation tells her to sign in instead.
  expect(text).toMatch(/\/invitation\/|\/forgot-password/);
});
