import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { RECRUITER, seedPassword, signedIn } from "./support";

// Jobs and their descriptions against the real API (SP-04a). The API reads descriptions with
// the mock AI profile in CI (HV_AI_MOCK_SCRIPTS answers jd.extract); locally it may be Gemini,
// so the checks hold for any extraction that finds something.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const DESCRIPTION = [
  "Platform Engineer",
  "",
  "Responsibilities",
  "- Run Kubernetes clusters",
  "- Build internal tools in Python",
  "",
  "Requirements",
  "- 4+ years of Python",
  "- Experience with Kubernetes",
  "",
  "Nice to have",
  "- Go",
].join("\n");

async function noAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("a recruiter creates a job, has its description read, applies it and opens the job", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const title = `E2E Platform Engineer ${randomUUID().slice(0, 6)}`;
  await signedIn(page, RECRUITER, seedPassword());

  await page.goto("/jobs/new");
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Add a skill").fill("Python");
  await page.getByLabel("Add a skill").press("Enter");
  await page.getByRole("button", { name: "Create job" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await noAxeViolations(page);

  await page.getByRole("tab", { name: "Description" }).click();
  await page.getByLabel("Job description").fill(DESCRIPTION);
  await page.getByRole("button", { name: "Read description" }).click();
  // Read in the background: the panel polls until the review appears.
  await expect(page.getByRole("heading", { name: "Review what was found" })).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByText(/^From the description: /).first()).toBeVisible();
  await noAxeViolations(page);
  // The review suggests the description's own title; keep the test's, so the list finds it.
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Apply to job" }).click();
  await expect(page.getByText("The description was applied to the job.")).toBeVisible();

  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("cell", { name: "Description applied" })).toBeVisible();

  await page.getByRole("button", { name: "Open job" }).click();
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();

  await page.goto("/jobs?status=open");
  await page.getByRole("searchbox").fill(title);
  await page.getByRole("searchbox").press("Enter");
  await expect(page.getByRole("link", { name: new RegExp(title) })).toBeVisible();
});
