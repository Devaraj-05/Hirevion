import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { RECRUITER, seedPassword, signedIn } from "./support";

// The CP3 golden path against the real API (SP-17 exit criterion): a simulated interview (with the
// desktop's proctoring events and recording segments) → its evaluation → the reports → the review
// workspace → the Hiring Manager's input and a recruiter's decision → the report the candidate is
// allowed to see, on their portal. Views, downloads, recordings played and score changes are in
// the audit log at the end.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const REPO = fileURLToPath(new URL("../../../", import.meta.url));
const API = process.env.HV_E2E_API_URL ?? "http://127.0.0.1:8000";
const PORTAL = "http://candidate.hirevion.localhost:3100";
const HIRING_MANAGER = "hiring-manager@acme.example.test";
const uv = process.env.HV_UV ?? "uv";

async function noAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

/** Runs `hv interview-sim` (with the desktop's telemetry) and returns what it printed. */
function simulate(persona: string, password: string): { id: string; email: string } {
  const output = execFileSync(
    uv,
    ["run", "hv", "interview-sim", "--persona", persona, "--api", API, "--password", password],
    { cwd: REPO, encoding: "utf8" },
  );
  const id = output.match(/^interview_id=([0-9a-f-]{36})$/m)?.[1];
  const email = output.match(/^candidate_email=(\S+)$/m)?.[1];
  if (!id || !email) throw new Error(`the simulator printed no interview: ${output}`);
  return { id, email };
}

interface AuditRow {
  action: string;
  resource_id: string | null;
  actor_type: string;
  details: Record<string, unknown>;
}

function auditTail(filter: ["--resource" | "--action", string]): AuditRow[] {
  const output = execFileSync(
    uv,
    ["run", "hv", "audit-tail", "--json", "--limit", "500", ...filter],
    { cwd: REPO, encoding: "utf8" },
  );
  return JSON.parse(output.slice(output.indexOf("["))) as AuditRow[];
}

const auditFor = (resource: string): AuditRow[] => auditTail(["--resource", resource]);

async function downloadedPdf(page: Page, click: () => Promise<void>): Promise<Buffer> {
  const [download] = await Promise.all([page.waitForEvent("download"), click()]);
  const path = await download.path();
  expect(path).toBeTruthy();
  return readFileSync(path);
}

// A wrong selector fails in seconds, not after the whole test's time.
test.use({ actionTimeout: 20_000 });

test("the CP3 golden path: simulated interview, evaluation, reports, review, decision", async ({
  browser,
  page,
}) => {
  test.setTimeout(480_000);
  const password = `portal passphrase ${randomUUID().slice(0, 8)}`;
  const { id, email } = simulate("partial", password);
  await signedIn(page, RECRUITER, seedPassword());

  // The interview and its evaluation (the API's workers run it on the mock AI).
  await page.goto(`/interviews/${id}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Sim Candidate");
  await expect
    .poll(
      async () => {
        const response = await page.request.get(`/api/v1/interviews/${id}/evaluation`);
        return ((await response.json()) as { state: string }).state;
      },
      { timeout: 150_000, intervals: [2_000] },
    )
    .toBe("ready");
  const interview = (await (await page.request.get(`/api/v1/interviews/${id}`)).json()) as {
    candidate: { id: string };
    application_id: string;
  };

  // It waits in the pending-review queue.
  await page.goto("/reports/pending");
  await expect(page.locator(`a[href="/interviews/${id}/review"]`)).toBeVisible();
  await noAxeViolations(page);

  // The interview report: thirteen sections, every one populated but coding, which says so.
  await page.goto(`/reports/interview/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "Interview report" })).toBeVisible();
  await expect(page.locator("[data-section]")).toHaveCount(13);
  await expect(page.locator('[data-section][data-status="populated"]')).toHaveCount(12);
  await expect(
    page.locator('[data-section="coding_evaluation"][data-status="pending"]'),
  ).toHaveCount(1);
  await expect(page.getByRole("region", { name: /Transcript/ })).toContainText("Please");
  await noAxeViolations(page);
  const pdf = await downloadedPdf(page, () =>
    page.getByRole("button", { name: "Export as PDF" }).click(),
  );
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");

  // The proctoring report: fourteen sections, no single score; reviewer notes wait for a reviewer.
  await page.goto(`/reports/proctoring/${id}`);
  await expect(page.locator("[data-section]")).toHaveCount(14);
  await expect(page.locator('[data-section][data-status="populated"]')).toHaveCount(13);
  await expect(page.locator('[data-section="reviewer_notes"][data-status="empty"]')).toHaveCount(1);
  await expect(page.getByText(/no single score for cheating or honesty/)).toBeVisible();
  await noAxeViolations(page);
  await page.goto(`/reports/coding/${id}`);
  await expect(page.getByText(/arrive with the coding service \(SP-16\)/).first()).toBeVisible();

  // The review workspace: the recordings on one timeline, the transcript, the events.
  await page.goto(`/interviews/${id}/review`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Review: Sim Candidate");
  await expect(page.locator("[data-track]")).toHaveCount(3);
  const transcript = page.getByRole("list", { name: "Transcript" });
  await expect(transcript.getByRole("button").first()).toBeVisible();
  const second = transcript.getByRole("button").nth(1);
  await second.click();
  await expect(second).toHaveAttribute("aria-current", "true");
  await page.getByRole("button", { name: /^Jump to Phone detected at/ }).click();

  // Confirming a critical event, a note on the moment, and a changed score: each audited.
  const phone = page.getByRole("listitem").filter({ hasText: "Phone detected" });
  await phone.getByRole("button", { name: "Review" }).click();
  await phone.getByLabel("Why?").fill("A phone is clearly in the camera's view.");
  await phone.getByRole("button", { name: "Save review" }).click();
  await expect(page.getByText("Review saved.")).toBeVisible();
  await expect(phone.getByText("Confirmed", { exact: true })).toBeVisible();
  await page.getByLabel("Add a note").fill("Looked at the phone, then back at the screen.");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("Note added.")).toBeVisible();
  await page.getByRole("button", { name: "Change a score" }).click();
  const change = page.getByRole("dialog", { name: "Change a score" });
  await change.getByLabel("What").selectOption("communication");
  await change.getByLabel("New score (0 to 10)").fill("7");
  await change.getByLabel("Why?").fill("Clear and structured on a second listen.");
  await change.getByRole("button", { name: "Save change" }).click();
  await expect(page.getByText("Score changed.")).toBeVisible();
  await noAxeViolations(page);

  // A Hiring Manager recommends, with reasons; that moves nothing.
  const manager = await browser.newContext();
  const managerPage = await manager.newPage();
  await signedIn(managerPage, HIRING_MANAGER, seedPassword());
  await managerPage.goto(`/interviews/${id}/review`);
  await managerPage.getByLabel("Recommendation").selectOption("hire");
  await managerPage.getByLabel("Your reasons").fill("Solid fundamentals; fits the platform team.");
  await managerPage.getByRole("button", { name: "Save recommendation" }).click();
  await expect(managerPage.getByText("Recommendation saved.")).toBeVisible();
  await expect(managerPage.getByRole("button", { name: "Change status" })).toHaveCount(0);
  await manager.close();

  // The recruiter decides. Only a person can, and the decision says why.
  await page.reload();
  await expect(page.getByText(/: Yes$/)).toBeVisible();
  await page.getByRole("button", { name: "Change status" }).click();
  const decision = page.getByRole("dialog", { name: "Change the hiring status" });
  await decision.getByLabel("Move to").selectOption("selected");
  await expect(decision.getByRole("note")).toContainText("final decision");
  await decision.getByLabel("Why?").fill("Strong fundamentals and a clear recommendation.");
  await decision.getByRole("button", { name: "Make the decision" }).click();
  await expect(page.getByText(/Selected by .* on /)).toBeVisible();

  // What the candidate may see: edited, approved, released.
  await page
    .getByLabel("Text for Next step", { exact: true })
    .fill("We would like to move forward and will email you by Friday.");
  await page.getByRole("button", { name: "Approve and release" }).click();
  await page.getByRole("button", { name: "Release", exact: true }).click();
  await expect(page.getByText("Report released to the candidate.")).toBeVisible();

  // The queue no longer holds it, and the proctoring report now has its reviewer notes.
  await page.goto("/reports/pending");
  await expect(page.locator(`a[href="/interviews/${id}/review"]`)).toHaveCount(0);
  await page.goto(`/reports/proctoring/${id}`);
  await expect(page.locator('[data-section][data-status="populated"]')).toHaveCount(14);

  // Candidate 360: thirteen tabs, and the activity timeline across the sources.
  await page.goto(`/candidates/${interview.candidate.id}`);
  await expect(page.getByRole("tab", { name: "Activity timeline" })).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(13);
  await page.getByRole("tab", { name: "Activity timeline" }).click();
  const timeline = page.getByRole("list", { name: "Activity timeline" });
  await expect(timeline.getByText("Decision: Selected")).toBeVisible();
  await expect(timeline.getByText("Phone seen in the camera").first()).toBeVisible();
  await noAxeViolations(page);

  // The candidate's portal: only the released items, and a PDF of them.
  const portalContext = await browser.newContext();
  const portal = await portalContext.newPage();
  await portal.goto(`${PORTAL}/login`);
  await portal.getByLabel("Email").fill(email);
  await portal.getByLabel("Password", { exact: true }).fill(password);
  await portal.getByRole("button", { name: "Sign in" }).click();
  await expect(portal.getByRole("heading", { level: 1, name: "Your interviews" })).toBeVisible();
  await portal.goto(`${PORTAL}/report`);
  await expect(
    portal.getByText("We would like to move forward and will email you by Friday."),
  ).toBeVisible();
  await expect(portal.getByText("Interview completion")).toBeVisible();
  await expect(portal.getByText("Technical feedback")).toHaveCount(0);
  await expect(portal.locator("main")).not.toContainText(/proctor|recommend|score|note/i);
  await noAxeViolations(portal);
  const candidatePdf = await downloadedPdf(portal, () =>
    portal.getByRole("link", { name: /as a PDF$/ }).click(),
  );
  expect(candidatePdf.subarray(0, 5).toString()).toBe("%PDF-");
  await portalContext.close();

  // The audit log shows it all.
  const actions = new Set(
    [id, interview.application_id, interview.candidate.id].flatMap((resource) =>
      auditFor(resource).map((row) => row.action),
    ),
  );
  // A reviewed event's entry is about the event itself; its details name the interview.
  for (const row of auditTail(["--action", "proctoring.event_reviewed"])) {
    if (row.details.interview_id === id) actions.add(row.action);
  }
  for (const action of [
    "report.viewed",
    "report.exported",
    "report.downloaded",
    "recording.viewed",
    "score.modified",
    "proctoring.event_reviewed",
    "candidate.note_added",
    "hiring.input_added",
    "hiring.decided",
    "report.released",
  ]) {
    expect(actions, action).toContain(action);
  }
});
