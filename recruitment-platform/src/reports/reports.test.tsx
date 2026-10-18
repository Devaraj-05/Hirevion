import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin, renderWithIntl } from "@/test/render";
import * as api from "./api";
import { CandidateReportCard } from "./candidate-report-card";
import { ReportPage } from "./report-page";
import { ReportView } from "./report-view";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getInterviewReport: vi.fn(),
  getCandidateReportState: vi.fn(),
  saveCandidateReport: vi.fn(),
  approveCandidateReport: vi.fn(),
  withdrawCandidateReport: vi.fn(),
  createExport: vi.fn(),
  listExports: vi.fn(),
}));

const DOCUMENT: api.ReportDocument = {
  schema_version: 1,
  kind: "interview",
  title: "Interview report",
  subtitle: "IV-0001 · Asha Rao · Backend Engineer",
  audience: "internal",
  confidential: true,
  generated_at: "2026-10-17T10:00:00Z",
  subject: { interview_id: "iv-1", candidate_name: "Asha Rao" },
  sections: [
    {
      key: "executive_summary",
      title: "Executive summary",
      status: "populated",
      note: null,
      blocks: [
        { type: "text", text: "A strong interview.", tone: "normal" },
        { type: "facts", rows: [{ label: "Candidate", value: "Asha Rao" }] },
        {
          type: "table",
          caption: "Skill scores",
          columns: ["Skill", "Score"],
          rows: [["PostgreSQL", "8.1"]],
        },
        {
          type: "quotes",
          items: [{ text: "I would run EXPLAIN ANALYZE.", source: "Turn 4 at 1:02" }],
        },
        { type: "list", items: ["Reads query plans"] },
        { type: "notice", tone: "info", text: "People decide." },
      ],
    },
    {
      key: "coding_evaluation",
      title: "Coding evaluation",
      status: "pending",
      note: "Arrives with SP-16.",
      blocks: [
        { type: "code", caption: "Question 4", language: "python", text: "def f():\n  pass" },
      ],
    },
    { key: "timeline", title: "Timeline", status: "empty", note: "Nothing happened.", blocks: [] },
  ],
};

beforeEach(() => {
  resetNavigation("/reports/interview/iv-1");
  vi.mocked(api.getInterviewReport).mockResolvedValue(DOCUMENT);
  vi.mocked(api.listExports).mockResolvedValue([]);
});

describe("ReportView", () => {
  it("renders every block as semantic content, and says which sections wait or are empty", () => {
    renderWithIntl(<ReportView document={DOCUMENT} />);
    expect(screen.getByText("Confidential: internal use only")).toBeInTheDocument();
    const contents = screen.getByRole("navigation", { name: "Contents" });
    expect(
      within(contents)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Executive summary", "Coding evaluation", "Timeline"]);
    const summary = screen.getByRole("region", { name: "Executive summary" });
    expect(within(summary).getByRole("table", { name: "Skill scores" })).toBeInTheDocument();
    expect(within(summary).getByRole("columnheader", { name: "Score" })).toBeInTheDocument();
    expect(within(summary).getByText("Candidate").tagName).toBe("DT");
    expect(within(summary).getByText("“I would run EXPLAIN ANALYZE.”")).toBeInTheDocument();
    expect(within(summary).getByText("Turn 4 at 1:02").tagName).toBe("CITE");
    expect(within(summary).getByRole("note")).toHaveTextContent("People decide.");
    expect(within(summary).queryByText("Pending")).not.toBeInTheDocument();
    const coding = screen.getByRole("region", { name: /Coding evaluation/ });
    expect(within(coding).getByText("Pending")).toBeInTheDocument();
    expect(within(coding).getByText("Arrives with SP-16.")).toBeInTheDocument();
    expect(within(coding).getByText(/def f\(\):/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: /Timeline/ })).getByText("Empty"),
    ).toBeInTheDocument();
  });

  it("never turns a string into markup", () => {
    const evil = "<img src=x onerror=alert(1)>";
    renderWithIntl(
      <ReportView
        compact
        document={{
          ...DOCUMENT,
          sections: [
            {
              key: "a",
              title: "A",
              status: "populated",
              note: null,
              blocks: [{ type: "text", text: evil, tone: "normal" }],
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(evil)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.queryByText("Confidential: internal use only")).not.toBeInTheDocument();
  });
});

describe("ReportPage", () => {
  it("shows the report with its export, and hides the export from someone who can't", async () => {
    const first = renderAdmin(<ReportPage kind="interview" id="iv-1" canExport canReview />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Interview report" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export as PDF" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review workspace" })).toHaveAttribute(
      "href",
      "/interviews/iv-1/review",
    );
    expect(screen.getByRole("link", { name: "Proctoring report" })).toHaveAttribute(
      "href",
      "/reports/proctoring/iv-1",
    );
    first.unmount();
    renderAdmin(<ReportPage kind="interview" id="iv-1" canExport={false} />);
    await screen.findByRole("heading", { level: 1, name: "Interview report" });
    expect(screen.queryByRole("button", { name: "Export as PDF" })).not.toBeInTheDocument();
  });

  it("exports a PDF and lists the PDFs made, each downloaded through the audited route", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, assign, origin: "http://localhost" },
    });
    vi.mocked(api.createExport).mockResolvedValue({
      id: "ex-1",
      kind: "interview",
      interview_id: "iv-1",
      candidate_id: null,
      bytes: 20_480,
      sha256: "0".repeat(64),
      renderer: "chromium",
      requested_by: "u-1",
      requested_by_name: "Rita Rao",
      created_at: "2026-10-17T10:05:00Z",
    });
    vi.mocked(api.listExports).mockResolvedValue([
      {
        id: "ex-0",
        kind: "interview",
        interview_id: "iv-1",
        candidate_id: null,
        bytes: 20_480,
        sha256: "0".repeat(64),
        renderer: "chromium",
        requested_by: "u-1",
        requested_by_name: "Rita Rao",
        created_at: "2026-10-16T09:00:00Z",
      },
    ]);
    renderAdmin(<ReportPage kind="interview" id="iv-1" canExport />);
    expect(await screen.findByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/v1/report-exports/ex-0/download",
    );
    await user.click(screen.getByRole("button", { name: "Export as PDF" }));
    await waitFor(() =>
      expect(api.createExport).toHaveBeenCalledWith({ kind: "interview", interview_id: "iv-1" }),
    );
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("/api/v1/report-exports/ex-1/download"),
    );
  });

  it("says when a report isn't there", async () => {
    vi.mocked(api.getInterviewReport).mockRejectedValue(
      Object.assign(new Error("nope"), { name: "ApiProblem", status: 404 }),
    );
    renderAdmin(<ReportPage kind="interview" id="iv-1" canExport />);
    expect(await screen.findByText(/couldn't be loaded|doesn't exist/)).toBeInTheDocument();
  });
});

const ITEMS: api.CandidateReportItem[] = [
  {
    key: "completion",
    title: "Interview completion",
    text: "You completed it.",
    include: true,
    allowed: true,
  },
  {
    key: "general_feedback",
    title: "General feedback",
    text: "Clear thinking.",
    include: false,
    allowed: false,
  },
  {
    key: "technical_feedback",
    title: "Technical feedback",
    text: "Study indexes.",
    include: false,
    allowed: false,
  },
  {
    key: "coding_feedback",
    title: "Coding feedback",
    text: "None.",
    include: false,
    allowed: false,
  },
  {
    key: "next_step",
    title: "Next-step status",
    text: "We'll write by Friday.",
    include: true,
    allowed: true,
  },
];
const DRAFT: api.CandidateReport = {
  interview_id: "iv-1",
  status: "draft",
  ready: true,
  items: ITEMS,
  released: [],
  approved_by: null,
  approved_by_name: null,
  approved_at: null,
  withdrawn_at: null,
  withdrawn_reason: null,
};

describe("CandidateReportCard", () => {
  it("lets a recruiter edit, then releases after confirming, saving first", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getCandidateReportState).mockResolvedValue(DRAFT);
    const released: api.CandidateReport = {
      ...DRAFT,
      status: "released",
      released: [{ key: "next_step", title: "Next-step status", text: "We'll write on Monday." }],
      approved_by: "u-1",
      approved_by_name: "Rita Rao",
      approved_at: "2026-10-17T10:00:00Z",
    };
    vi.mocked(api.saveCandidateReport).mockResolvedValue(DRAFT);
    vi.mocked(api.approveCandidateReport).mockResolvedValue(released);
    renderAdmin(<CandidateReportCard id="iv-1" canRelease />);
    const step = await screen.findByLabelText("Text for Next-step status");
    await user.clear(step);
    await user.type(step, "We'll write on Monday.");
    // An item the organisation doesn't share says so and can't be included.
    expect(
      screen.getAllByText("Your organisation doesn't share this item with candidates."),
    ).toHaveLength(3);
    for (const box of screen
      .getAllByRole("checkbox", { name: "Include in the release" })
      .slice(1, 4)) {
      expect(box).toBeDisabled();
    }
    await user.click(screen.getByRole("button", { name: "Approve and release" }));
    await user.click(await screen.findByRole("button", { name: "Release" }));
    await waitFor(() => expect(api.approveCandidateReport).toHaveBeenCalledWith("iv-1"));
    expect(api.saveCandidateReport).toHaveBeenCalledWith(
      "iv-1",
      expect.objectContaining({ next_step: { text: "We'll write on Monday.", include: true } }),
    );
    expect(
      await screen.findByText("Released by Rita Rao on 17 Oct 2026, 3:30 pm."),
    ).toBeInTheDocument();
    expect(screen.getByText("We'll write on Monday.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeInTheDocument();
  });

  it("is read-only for someone who can't release, and withdraws a release with a reason", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getCandidateReportState).mockResolvedValue(DRAFT);
    const viewer = renderAdmin(<CandidateReportCard id="iv-1" canRelease={false} />);
    expect(
      await screen.findByText("Only a recruiter can edit and release this report."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve and release" })).not.toBeInTheDocument();
    viewer.unmount();

    vi.mocked(api.getCandidateReportState).mockResolvedValue({
      ...DRAFT,
      status: "released",
      released: [{ key: "completion", title: "Interview completion", text: "You completed it." }],
      approved_by_name: "Rita Rao",
      approved_at: "2026-10-17T10:00:00Z",
    });
    vi.mocked(api.withdrawCandidateReport).mockResolvedValue({ ...DRAFT, status: "withdrawn" });
    renderAdmin(<CandidateReportCard id="iv-1" canRelease />);
    await user.click(await screen.findByRole("button", { name: "Withdraw" }));
    const dialog = await screen.findByRole("dialog", { name: "Withdraw this report" });
    const submit = within(dialog).getByRole("button", { name: "Withdraw" });
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Why is it being withdrawn?"), "Sent in error");
    await user.click(submit);
    await waitFor(() =>
      expect(api.withdrawCandidateReport).toHaveBeenCalledWith("iv-1", "Sent in error"),
    );
  });

  it("waits for the interview to end", async () => {
    vi.mocked(api.getCandidateReportState).mockResolvedValue({
      ...DRAFT,
      status: "none",
      ready: false,
    });
    renderAdmin(<CandidateReportCard id="iv-1" canRelease />);
    expect(
      await screen.findByText("A report can be drafted once the interview has ended."),
    ).toBeInTheDocument();
  });
});
