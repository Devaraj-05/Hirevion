import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { RECRUITER, seedPassword, signedIn } from "./support";

// Screening against the real API (SP-05), with the mock AI's scripted answers in CI.

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

test("a recruiter screens a job's candidates, reads why, and shortlists one", async ({ page }) => {
  test.setTimeout(150_000);
  await signedIn(page, RECRUITER, seedPassword());
  await page.goto("/jobs/new");
  await page.getByLabel("Title").fill(`E2E Data Engineer ${randomUUID().slice(0, 6)}`);
  await page.getByLabel("Add a skill").fill("Python");
  await page.getByLabel("Add a skill").press("Enter");
  await page.getByRole("button", { name: "Create job" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("E2E Data Engineer");

  await page.getByRole("tab", { name: "Resumes" }).click();
  await page.getByLabel("Choose files").setInputFiles({
    name: "meera-iyer.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(RESUME),
  });
  await expect(page.getByRole("link", { name: "Meera Iyer" })).toBeVisible({ timeout: 90_000 });

  await page.getByRole("tab", { name: "Ranking" }).click();
  await page.getByRole("button", { name: "Screen candidates" }).click();
  await expect(page.getByText("1 of 1 screened")).toBeVisible({ timeout: 60_000 });
  const explain = page.getByRole("button", { name: "Explain Meera Iyer's ranking" });
  await expect(explain).toBeVisible({ timeout: 30_000 });
  await noAxeViolations(page);

  await explain.click();
  const sheet = page.getByRole("dialog", { name: "Why Meera Iyer ranks #1" });
  await expect(sheet.getByText("Builds data pipelines in Python")).toBeVisible();
  await noAxeViolations(page);
  await sheet.getByRole("button", { name: "Shortlist" }).click();
  await expect(page.getByText("1 candidate updated.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("cell", { name: "Shortlisted" })).toBeVisible();
});
