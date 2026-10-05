import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { RECRUITER, seedPassword, signedIn } from "./support";

// The question library and interview templates against the real API (SP-06), with the mock
// AI's scripted questions in CI. Generated questions stay drafts until approved; a template edit
// is a new version and the old one stays as it was (PRD §80).

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
// The first question in e2e/auth/ai-scripts.json ("questions.generate").
const GENERATED = "How would you find out why a Python web endpoint became slow in production?";

async function noAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("a recruiter approves an AI draft, pins it in a template, and edits the template", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signedIn(page, RECRUITER, seedPassword());

  await page.goto("/questions");
  await page.getByRole("button", { name: "Generate with AI" }).click();
  const dialog = page.getByRole("dialog", { name: "Generate questions with AI" });
  await dialog.getByLabel("Skills (separate with commas)").fill("Python");
  await dialog.getByLabel("How many (1 to 10)").fill("2");
  await noAxeViolations(page);
  await dialog.getByRole("button", { name: "Generate drafts" }).click();
  // A rerun on the same database finds the questions already there and adds none.
  await expect(page.getByText(/drafts? added|No new drafts/)).toBeVisible({ timeout: 30_000 });
  await expect(dialog).toBeHidden();

  // The library shows the drafts after generating; widen it, since an earlier run on the same
  // database may already have approved the question.
  await expect(page.getByLabel("Status")).toHaveValue("draft");
  await page.getByLabel("Status").selectOption("");
  await expect(page).not.toHaveURL(/status=/);
  await page.getByRole("searchbox", { name: "Search questions" }).fill("slow production endpoint");
  await page.getByRole("searchbox", { name: "Search questions" }).press("Enter");
  await page.getByRole("button", { name: `Open question: ${GENERATED.slice(0, 60)}` }).click();
  const sheet = page.getByRole("dialog", { name: "Question" });
  await expect(sheet.getByLabel("Question")).toHaveValue(GENERATED);
  await noAxeViolations(page);
  const approve = sheet.getByRole("button", { name: "Approve" });
  if (await approve.isVisible()) {
    await approve.click();
    await expect(page.getByText("Question approved.")).toBeVisible();
  }
  await expect(sheet.getByText("Approved", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");

  const name = `E2E backend screen ${randomUUID().slice(0, 6)}`;
  await page.goto("/interviews/templates/new");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Skill 1", { exact: true }).fill("Python");
  await page.getByLabel("Find an approved question").fill("slow production endpoint");
  const results = page.getByRole("list", { name: "Matching questions" });
  await results
    .getByRole("listitem")
    .filter({ hasText: GENERATED })
    .getByRole("button", { name: "Pin" })
    .click();
  await expect(page.getByText("Version 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Skill matrix" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Create template" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible({ timeout: 15_000 });
  await noAxeViolations(page);

  await page.getByLabel("Duration in minutes").fill("60");
  await page.getByRole("button", { name: "Save as version 2" }).click();
  await expect(page.getByText("Saved as version 2.")).toBeVisible();

  await page.getByRole("tab", { name: "Versions" }).click();
  const versions = page.getByRole("list", { name: "Versions" });
  await expect(versions.getByRole("listitem")).toHaveCount(2);
  await expect(versions.getByRole("listitem").first()).toContainText("60 minutes");
  await expect(versions.getByRole("listitem").last()).toContainText("45 minutes");
  await page.getByRole("tab", { name: "Skill matrix" }).click();
  await expect(page.getByRole("rowheader", { name: "Python" })).toBeVisible();
});
