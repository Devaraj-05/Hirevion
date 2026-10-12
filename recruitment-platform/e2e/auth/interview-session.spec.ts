import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { ORG_ADMIN, RECRUITER, seedPassword, signedIn } from "./support";

// The interview itself against the real API (SP-09): the simulator signs in like the desktop
// app (DPoP), answers a whole text-mode interview as the strong persona on the mock AI, and the
// recruiter reads its transcript, each question's source and the skills' coverage. An org admin
// sets the FAQ the AI answers final questions from.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const REPO = fileURLToPath(new URL("../../../", import.meta.url));
const API = process.env.HV_E2E_API_URL ?? "http://127.0.0.1:8000";

async function noAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

/** Runs `hv interview-sim` and returns the interview it completed. */
function simulate(persona: string): string {
  const output = execFileSync(
    process.env.HV_UV ?? "uv",
    ["run", "hv", "interview-sim", "--persona", persona, "--api", API],
    { cwd: REPO, encoding: "utf8" },
  );
  const id = output.match(/^interview_id=([0-9a-f-]{36})$/m)?.[1];
  if (!id) throw new Error(`the simulator printed no interview: ${output}`);
  return id;
}

test("a recruiter reads a simulated interview's transcript and coverage", async ({ page }) => {
  test.setTimeout(180_000);
  const id = simulate("strong");
  await signedIn(page, RECRUITER, seedPassword());
  await page.goto(`/interviews/${id}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Sim Candidate");
  await expect(page.getByText("Completed", { exact: true }).first()).toBeVisible();

  await expect(page.getByRole("heading", { name: "Skill coverage" })).toBeVisible();
  await expect(page.getByText("Python", { exact: true })).toBeVisible();
  await expect(page.getByText("PostgreSQL", { exact: true })).toBeVisible();
  await expect(page.getByText("Covered", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Not covered")).toHaveCount(0);

  await expect(page.getByRole("heading", { name: "Transcript", exact: true })).toBeVisible();
  // The full transcript, not the live monitor's latest lines, which repeat the last turns.
  const transcript = page.getByRole("region", { name: "Transcript", exact: true });
  await expect(transcript.getByText(/^Hello Sim, I'm the AI interviewer/)).toBeVisible();
  await expect(transcript.getByText("When will I hear back about the result?")).toBeVisible();
  // The final question was answered from the organisation's FAQ, and only from it.
  await expect(transcript.getByText(/usually replies within five working days/)).toBeVisible();
  await expect(
    transcript.getByText(/^From the resume, page 1: “Moved reporting queries/),
  ).toBeVisible();
  await expect(transcript.getByText("From the question library").first()).toBeVisible();
  await noAxeViolations(page);
});

test("an org admin sets the FAQ the AI answers final questions from", async ({ page }) => {
  test.setTimeout(90_000);
  const answer = `It is hybrid, three days a week (${randomUUID().slice(0, 6)}).`;
  await signedIn(page, ORG_ADMIN, seedPassword());
  await page.goto("/admin/organization");
  await expect(page.getByRole("heading", { name: "Interview briefing" })).toBeVisible();
  await expect(page.getByLabel("Instructions for candidates")).toBeVisible();
  await page.getByRole("button", { name: "Add a question" }).click();
  const last = await page.getByLabel(/^Question \d+$/).count();
  await page.getByLabel(`Question ${last}`).fill(`E2E: is the role remote? ${answer.slice(-8)}`);
  await page.getByLabel("Answer").last().fill(answer);
  await page.getByRole("button", { name: "Save briefing" }).click();
  await expect(page.getByText("Interview briefing saved")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Answer").last()).toHaveValue(answer);
  await noAxeViolations(page);
  // Leave the FAQ as it was, so runs don't pile up entries.
  await page.getByRole("button", { name: `Remove question ${last}` }).click();
  await page.getByRole("button", { name: "Save briefing" }).click();
  await expect(page.getByText("Interview briefing saved").last()).toBeVisible();
  await expect(page.getByLabel(`Question ${last}`)).toHaveCount(0);
});
