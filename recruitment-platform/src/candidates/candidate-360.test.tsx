import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as review from "@/review/api";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { CandidatePage } from "./candidate-page";

vi.setConfig({ testTimeout: 25_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getCandidate: vi.fn(),
}));
vi.mock("@/review/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/review/api")>()),
  getCandidate360: vi.fn(),
  getTimeline: vi.fn(),
  addCandidateNote: vi.fn(),
  getHiringState: vi.fn(),
  changeHiringStatus: vi.fn(),
}));

const CANDIDATE = {
  id: "c-1",
  name: "Asha Rao",
  email: "asha@example.test",
  phone: null,
  location: "Pune",
  headline: "Engineer",
  skills: [],
  flags: {},
  created_at: "2026-10-03T00:00:00Z",
  updated_at: "2026-10-03T00:00:00Z",
  profile: {},
  skill_details: [],
  applications: [
    {
      id: "app-1",
      job_id: "j-1",
      job_reference: "JOB-0001",
      job_title: "Backend Engineer",
      stage: "interviewed",
      hiring_status: "interview_completed",
      created_at: "2026-10-03T00:00:00Z",
    },
  ],
  documents: [],
} as unknown as api.Candidate;

const SCORE = (ai: number, value: number) => ({ ai, value, change: null });
const FULL: review.Candidate360 = {
  candidate_id: "c-1",
  name: "Asha Rao",
  access: { interviews: true, proctoring: true, recordings: true, reports: true, notes: true },
  applications: [],
  screening: [
    {
      application_id: "app-1",
      job_id: "j-1",
      job_title: "Backend Engineer",
      score: 82,
      rank: 2,
      strengths: ["Strong PostgreSQL"],
      concerns: ["No cloud experience"],
      missing: [],
      knockouts: [],
      screened_at: "2026-10-04T00:00:00Z",
    },
  ],
  interviews: [
    {
      interview_id: "iv-1",
      reference: "IV-0001",
      application_id: "app-1",
      job_id: "j-1",
      job_title: "Backend Engineer",
      template_name: "Backend",
      status: "evaluated",
      hiring_status: "interview_completed",
      starts_at: "2026-10-16T10:00:00Z",
      started_at: "2026-10-16T10:05:00Z",
      completed_at: "2026-10-16T10:45:00Z",
      evaluation: {
        state: "ready",
        overall: SCORE(6.1, 6.1),
        communication: SCORE(5.8, 6.5),
        skills: [{ skill: "PostgreSQL", score: SCORE(8.6, 8.6) }],
        flags: [],
        strengths: ["Answered the PostgreSQL question soundly."],
        knowledge_gaps: ["Missed wraps, closure."],
      },
      proctoring: { critical: 1, warning: 7, info: 1, reviewed: 1 },
      recordings: [
        {
          track: "camera",
          kind: "camera",
          label: "Camera",
          status: "assembled",
          duration_ms: 2_400_000,
        },
      ],
      candidate_report_status: "released",
      code_snapshots: 1,
      exports: [{ id: "ex-1", kind: "interview", created_at: "2026-10-17T10:00:00Z" }],
    },
  ],
  skills: [
    {
      skill: "PostgreSQL",
      on_resume: true,
      resume_years: 4,
      interviews: [{ interview_id: "iv-1", reference: "IV-0001", score: 8.6 }],
    },
  ],
  notes: [
    {
      id: "n-1",
      candidate_id: "c-1",
      interview_id: "iv-1",
      author_id: "u-1",
      author_name: "Rita Rao",
      body: "Confident on query plans.",
      at_ms: 62_000,
      created_at: "2026-10-17T10:00:00Z",
    },
  ],
};

const ALL_TABS = [
  "Profile",
  "Resume",
  "Applications",
  "Screening",
  "Interview history",
  "Technical skills",
  "Coding",
  "AI interview",
  "Proctoring",
  "Recordings",
  "Reports",
  "Recruiter notes",
  "Activity timeline",
];
// The Resumes tab is named by the existing messages.
const tabNames = () => screen.getAllByRole("tab").map((tab) => tab.textContent);

beforeEach(() => {
  resetNavigation("/candidates/c-1");
  vi.mocked(api.getCandidate).mockResolvedValue(CANDIDATE);
  vi.mocked(review.getCandidate360).mockResolvedValue(FULL);
});

describe("Candidate 360", () => {
  it("has PRD §20's thirteen tabs for a reader who may see everything", async () => {
    renderAdmin(<CandidatePage id="c-1" canManage />);
    await screen.findByRole("tab", { name: "Activity timeline" });
    const names = tabNames();
    expect(names).toHaveLength(13);
    for (const name of ALL_TABS.filter((tab) => tab !== "Resume")) expect(names).toContain(name);
  });

  it("leaves out the tabs whose data the reader may not see", async () => {
    vi.mocked(review.getCandidate360).mockResolvedValue({
      ...FULL,
      access: {
        interviews: false,
        proctoring: false,
        recordings: false,
        reports: false,
        notes: true,
      },
      interviews: [],
    });
    renderAdmin(<CandidatePage id="c-1" />);
    await screen.findByRole("tab", { name: "Activity timeline" });
    const names = tabNames();
    for (const hidden of [
      "Interview history",
      "Coding",
      "AI interview",
      "Proctoring",
      "Recordings",
      "Reports",
    ]) {
      expect(names).not.toContain(hidden);
    }
    expect(names).toEqual(
      expect.arrayContaining(["Screening", "Technical skills", "Recruiter notes"]),
    );
  });

  it("shows screening, history, skills and the evaluation", async () => {
    const user = userEvent.setup();
    renderAdmin(<CandidatePage id="c-1" />);
    await user.click(await screen.findByRole("tab", { name: "Screening" }));
    expect(
      screen.getByText("Match score: 82 of 100 · rank 2 · screened 4 Oct 2026"),
    ).toBeInTheDocument();
    expect(screen.getByText("Strong PostgreSQL")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Interview history" }));
    const row = screen.getByRole("row", { name: /IV-0001/ });
    expect(within(row).getByText("Interview completed")).toBeInTheDocument();
    expect(within(row).getByText("6.1")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Technical skills" }));
    expect(screen.getByRole("row", { name: /PostgreSQL/ })).toHaveTextContent(
      "On the resume (4 years)",
    );
    expect(screen.getByRole("row", { name: /PostgreSQL/ })).toHaveTextContent("IV-0001: 8.6");
    await user.click(screen.getByRole("tab", { name: "AI interview" }));
    expect(screen.getByText("Answered the PostgreSQL question soundly.")).toBeInTheDocument();
    expect(screen.getByText("6.5 (AI: 5.8)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review workspace" })).toHaveAttribute(
      "href",
      "/interviews/iv-1/review",
    );
  });

  it("says coding is waiting for SP-16, and links the proctoring, recordings and reports", async () => {
    const user = userEvent.setup();
    renderAdmin(<CandidatePage id="c-1" />);
    await user.click(await screen.findByRole("tab", { name: "Coding" }));
    expect(screen.getByRole("note")).toHaveTextContent("SP-16");
    expect(screen.getByText("1 code snapshot saved")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Proctoring" }));
    expect(
      screen.getByText("These are signals for a reviewer, not a verdict."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Proctoring report" })).toHaveAttribute(
      "href",
      "/reports/proctoring/iv-1",
    );
    await user.click(screen.getByRole("tab", { name: "Recordings" }));
    expect(
      screen.getByText("Playing a recording is recorded in the audit log."),
    ).toBeInTheDocument();
    expect(screen.getByText("Camera: assembled, 40:00")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Reports" }));
    expect(screen.getByRole("link", { name: "Candidate report" })).toHaveAttribute(
      "href",
      "/reports/candidate/c-1",
    );
    expect(screen.getByText("Candidate-visible report: released")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/v1/report-exports/ex-1/download",
    );
  });

  it("adds a recruiter note", async () => {
    const user = userEvent.setup();
    vi.mocked(review.addCandidateNote).mockResolvedValue({} as review.Note);
    renderAdmin(<CandidatePage id="c-1" />);
    await user.click(await screen.findByRole("tab", { name: "Recruiter notes" }));
    expect(screen.getByText("Confident on query plans.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Add a note"), "Referred by Priya.");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() =>
      expect(review.addCandidateNote).toHaveBeenCalledWith("c-1", "Referred by Priya."),
    );
  });

  it("unifies the timeline's eight sources, filters them and pages back", async () => {
    const user = userEvent.setup();
    const item = (title: string, source: review.TimelineSource, at: string) => ({
      at,
      source,
      kind: "x",
      title,
      detail: null,
      severity: source === "proctoring" ? ("CRITICAL" as const) : null,
      interview_id: source === "proctoring" ? "iv-1" : null,
      offset_ms: source === "proctoring" ? 150_000 : null,
      actor: null,
      ref: {},
    });
    vi.mocked(review.getTimeline)
      .mockResolvedValueOnce({
        items: [
          item("Phone detected", "proctoring", "2026-10-16T10:07:30Z"),
          item("Screened for Backend Engineer", "screening", "2026-10-04T00:00:00Z"),
        ],
        next_before: "2026-10-04T00:00:00Z",
      })
      .mockResolvedValue({
        items: [item("Resume parsed", "screening", "2026-10-03T00:00:00Z")],
        next_before: null,
      });
    renderAdmin(<CandidatePage id="c-1" />);
    await user.click(await screen.findByRole("tab", { name: "Activity timeline" }));
    const list = await screen.findByRole("list", { name: "Activity timeline" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(
      within(list).getByRole("link", { name: "Phone detected: open the review at 2:30" }),
    ).toHaveAttribute("href", "/interviews/iv-1/review?t=150000");
    expect(screen.getAllByRole("checkbox")).toHaveLength(8);
    await user.click(screen.getByRole("button", { name: "Show older" }));
    expect(await screen.findByText("Resume parsed")).toBeInTheDocument();
    expect(review.getTimeline).toHaveBeenLastCalledWith("c-1", {
      before: "2026-10-04T00:00:00Z",
      limit: 50,
    });
    expect(screen.queryByRole("button", { name: "Show older" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Coding" }));
    await waitFor(() =>
      expect(review.getTimeline).toHaveBeenLastCalledWith(
        "c-1",
        expect.objectContaining({ source: expect.not.arrayContaining(["coding"]) }),
      ),
    );
  });

  it("shows each application's hiring status, and moves it for someone who may", async () => {
    const user = userEvent.setup();
    vi.mocked(review.getHiringState).mockResolvedValue({
      application_id: "app-1",
      candidate_id: "c-1",
      job_id: "j-1",
      job_title: "Backend Engineer",
      status: "interview_completed",
      allowed: ["shortlisted", "on_hold"],
      has_interview: true,
      decision: null,
      history: [],
      inputs: [],
    });
    renderAdmin(<CandidatePage id="c-1" canManage />);
    await user.click(await screen.findByRole("tab", { name: "Applications" }));
    const row = screen.getByRole("row", { name: /JOB-0001/ });
    expect(within(row).getByText("Interview completed")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Change status" }));
    const dialog = await screen.findByRole("dialog", { name: "Change the hiring status" });
    expect(
      within(dialog)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Shortlisted", "On hold"]);
  });
});
