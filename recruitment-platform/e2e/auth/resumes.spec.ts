import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { RECRUITER, seedPassword, signedIn } from "./support";

// Resumes into candidates against the real API (SP-04b). In CI the API reads resumes with the
// mock AI and its scripted answer (HV_AI_MOCK_SCRIPTS), with Azurite for the files.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
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

test("a recruiter uploads a resume and opens the candidate it became", async ({ page }) => {
  test.setTimeout(120_000);
  await signedIn(page, RECRUITER, seedPassword());
  await page.goto("/jobs/new");
  await page.getByLabel("Title").fill(`E2E Data Engineer ${randomUUID().slice(0, 6)}`);
  await page.getByRole("button", { name: "Create job" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("E2E Data Engineer");

  await page.getByRole("tab", { name: "Resumes" }).click();
  await page.getByLabel("Choose files").setInputFiles({
    name: "meera-iyer.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(RESUME),
  });
  await expect(page.getByText("Sent")).toBeVisible();
  // Read in the background: the list polls until the resume becomes a candidate.
  const candidate = page.getByRole("link", { name: "Meera Iyer" });
  await expect(candidate).toBeVisible({ timeout: 90_000 });
  await noAxeViolations(page);

  await page.getByRole("tab", { name: "Candidates" }).click();
  await expect(page.getByRole("link", { name: "Meera Iyer" })).toBeVisible();

  await page.getByRole("link", { name: "Meera Iyer" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Meera Iyer" })).toBeVisible();
  await expect(
    page.getByText("From the resume, page 1: “Data Engineer, Globex Analytics”"),
  ).toBeVisible();
  await noAxeViolations(page);
});
