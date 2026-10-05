import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { RankingPanel } from "./ranking-panel";
import { JobScreeningSettings } from "./settings-form";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getJobScreeningConfig: vi.fn(),
  saveJobScreeningConfig: vi.fn(),
  resetJobScreeningConfig: vi.fn(),
  getScreeningSummary: vi.fn(),
  listScreeningResults: vi.fn(),
  getApplicationScreening: vi.fn(),
  actOnApplications: vi.fn(),
  screenJob: vi.fn(),
  exportRanking: vi.fn(),
}));

const CONFIG: api.ScreeningConfig = {
  weights: {
    required_skills: 35,
    experience: 25,
    projects: 15,
    preferred_skills: 10,
    domain: 10,
    education: 5,
    location: 0,
  },
  knockouts: { required_skills: true, min_experience: true },
  blind: true,
  version: 0,
  inherited: true,
  source: "default",
};

function ranked(overrides: Partial<api.RankedApplication>): api.RankedApplication {
  return {
    application_id: "a-1",
    rank: 1,
    stage: "ranked",
    score: 88,
    candidate: {
      id: "c-1",
      name: "Asha Rao",
      headline: "Backend Engineer",
      location: null,
      flags: {},
    },
    skill_match: { required_score: 100 },
    experience: { score: 90 },
    knockouts: [],
    semantic_similarity: 0.8,
    recruiter_id: null,
    hiring_manager_id: null,
    screened_at: "2026-10-05T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  resetNavigation("/jobs/j-1");
  vi.mocked(api.getScreeningSummary).mockResolvedValue({
    applications: 2,
    screened: 2,
    waiting: 0,
    stages: { ranked: 2 },
  });
  vi.mocked(api.listScreeningResults).mockResolvedValue({
    items: [
      ranked({}),
      ranked({
        application_id: "a-2",
        rank: 2,
        score: 41,
        candidate: { id: "c-2", name: "Ravi Kumar", headline: null, location: null, flags: {} },
        knockouts: ["Missing required skills: Kubernetes"],
      }),
    ],
    next_cursor: null,
  });
});

describe("JobScreeningSettings", () => {
  it("won't save weights that don't add up to 100", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getJobScreeningConfig).mockResolvedValue(CONFIG);
    vi.mocked(api.saveJobScreeningConfig).mockResolvedValue({
      ...CONFIG,
      inherited: false,
      source: "job",
      version: 1,
    });
    renderAdmin(<JobScreeningSettings jobId="j-1" canEdit />);

    const experience = await screen.findByLabelText("Experience");
    await user.clear(experience);
    await user.type(experience, "30");
    expect(screen.getByRole("alert")).toHaveTextContent("now 105");
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();

    await user.clear(screen.getByLabelText("Domain experience"));
    await user.type(screen.getByLabelText("Domain experience"), "5");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.saveJobScreeningConfig).toHaveBeenCalled());
    const [, body] = vi.mocked(api.saveJobScreeningConfig).mock.calls[0] ?? [];
    expect(body?.weights).toMatchObject({ experience: 30, domain: 5 });
    expect(body?.blind).toBe(true);
  });
});

describe("RankingPanel", () => {
  it("acts on the selected candidates in bulk", async () => {
    const user = userEvent.setup();
    vi.mocked(api.actOnApplications).mockResolvedValue([]);
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage />);

    await user.click(await screen.findByRole("checkbox", { name: "Select Asha Rao" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Ravi Kumar" }));
    await user.click(
      within(screen.getByRole("region", { name: "2 selected" })).getByRole("button", {
        name: "Hold",
      }),
    );
    await waitFor(() =>
      expect(api.actOnApplications).toHaveBeenCalledWith("j-1", {
        application_ids: ["a-1", "a-2"],
        action: "hold",
      }),
    );
    expect(screen.getByText("Flagged")).toBeInTheDocument();
  });

  it("asks why before rejecting", async () => {
    const user = userEvent.setup();
    vi.mocked(api.actOnApplications).mockResolvedValue([]);
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage />);

    await user.click(await screen.findByRole("checkbox", { name: "Select Ravi Kumar" }));
    await user.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Reason"), "No Kubernetes");
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(api.actOnApplications).toHaveBeenCalledWith("j-1", {
        application_ids: ["a-2"],
        action: "reject",
        reason: "No Kubernetes",
      }),
    );
  });

  it("explains a ranking with the evidence behind each factor", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getApplicationScreening).mockResolvedValue({
      application_id: "a-1",
      job_id: "j-1",
      stage: "ranked",
      rank: 1,
      candidate: ranked({}).candidate,
      result: {
        id: "r-1",
        score: 88,
        factors: {
          required_skills: {
            score: 100,
            evidence: ["Python"],
            matched: ["Python"],
            supported: true,
          },
          projects: { score: 50, evidence: [], supported: false },
        },
        skill_match: {},
        experience: {},
        strengths: ["Payments experience"],
        concerns: [],
        missing: [],
        knockouts: [],
        semantic_similarity: 0.8,
        job_version: 1,
        config_version: 1,
        prompt_version: "screening-assess-v1",
        model: "mock-llm",
        created_at: "2026-10-05T00:00:00Z",
      },
      history: [],
    });
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage={false} />);

    await user.click(await screen.findByRole("button", { name: "Explain Asha Rao's ranking" }));
    const sheet = await screen.findByRole("dialog", { name: "Why Asha Rao ranks #1" });
    expect(within(sheet).getByText("From the resume: “Python”")).toBeInTheDocument();
    expect(within(sheet).getByText(/score capped/)).toBeInTheDocument();
    expect(within(sheet).getByText("Payments experience")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select Asha Rao" })).not.toBeInTheDocument();
  });

  it("exports the ranking", async () => {
    const user = userEvent.setup();
    vi.mocked(api.exportRanking).mockResolvedValue(new Blob(["Rank,Candidate"]));
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage />);
    await user.click(await screen.findByRole("button", { name: "Download Excel" }));
    await waitFor(() => expect(api.exportRanking).toHaveBeenCalledWith("j-1", "xlsx"));
  });
});
