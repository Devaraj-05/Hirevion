import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as jobsApi from "@/jobs/api";
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

vi.mock("@/jobs/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/jobs/api")>()),
  getJobChoices: vi.fn(),
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
    blind: true,
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

describe("blind screening", () => {
  it("is switched off only by someone who may change it, with a warning when it is off", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getJobScreeningConfig).mockResolvedValue(CONFIG);
    const view = renderAdmin(<JobScreeningSettings jobId="j-1" canEdit />);
    const locked = await screen.findByRole("switch", { name: /Blind screening/ });
    expect(locked).toBeDisabled();
    expect(screen.getByText(/Only an organisation administrator can turn blind/)).toBeVisible();
    view.unmount();

    vi.mocked(api.getJobScreeningConfig).mockResolvedValue({ ...CONFIG, blind: false });
    renderAdmin(<JobScreeningSettings jobId="j-1" canEdit canChangeBlind />);
    expect(await screen.findByRole("status")).toHaveTextContent(/AI sees each candidate's name/);
    const open = screen.getByRole("switch", { name: /Blind screening/ });
    expect(open).toBeEnabled();
    await user.click(open);
    expect(screen.queryByText(/AI sees each candidate's name/)).not.toBeInTheDocument();
  });

  it("says when the job's settings could not be loaded", async () => {
    vi.mocked(api.getJobScreeningConfig).mockRejectedValue(new Error("offline"));
    renderAdmin(<JobScreeningSettings jobId="j-1" canEdit />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't be loaded/);
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
        blind: true,
        job_version: 1,
        config_version: 1,
        prompt_version: "screening-assess-v1",
        model: "mock-llm",
        created_at: "2026-10-05T00:00:00Z",
      },
      history: [],
    });
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage={false} />);

    await user.click(await screen.findByRole("button", { name: /Asha Rao.*Explain the ranking/ }));
    const sheet = await screen.findByRole("dialog", { name: "Why Asha Rao ranks #1" });
    expect(within(sheet).getByText("From the resume: “Python”")).toBeInTheDocument();
    expect(within(sheet).getByText(/score capped/)).toBeInTheDocument();
    expect(within(sheet).getByText("Payments experience")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select Asha Rao" })).not.toBeInTheDocument();
  });

  it("reads the results again after screening again, though nobody was waiting", async () => {
    const user = userEvent.setup();
    vi.mocked(api.screenJob).mockResolvedValue(2);
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage pollMs={20} />);
    const again = await screen.findByRole("button", { name: "Screen again" });
    await waitFor(() => expect(api.listScreeningResults).toHaveBeenCalled());
    const before = vi.mocked(api.listScreeningResults).mock.calls.length;
    await user.click(again);
    await waitFor(() => expect(api.screenJob).toHaveBeenCalledWith("j-1"));
    // The panel reads the results again, though no candidate was waiting, then lets go.
    await waitFor(() =>
      expect(vi.mocked(api.listScreeningResults).mock.calls.length).toBeGreaterThan(before),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Screen again" })).toBeEnabled());
  });

  it("stops polling the run while its tab is hidden, and goes on when it is shown again", async () => {
    const user = userEvent.setup();
    vi.mocked(api.screenJob).mockResolvedValue(2);
    vi.mocked(api.getScreeningSummary).mockResolvedValue({
      applications: 2,
      screened: 1,
      waiting: 1,
      stages: { ranked: 1 },
    });

    function Tabs() {
      const [active, setActive] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setActive((previous) => !previous)}>
            toggle tab
          </button>
          <RankingPanel jobId="j-1" jobReference="JOB-0001" canManage pollMs={20} active={active} />
        </>
      );
    }

    renderAdmin(<Tabs />);
    await user.click(await screen.findByRole("button", { name: "Screen again" }));
    await waitFor(() => expect(api.screenJob).toHaveBeenCalledWith("j-1"));
    await user.click(screen.getByRole("button", { name: "toggle tab" }));
    await new Promise((resolve) => setTimeout(resolve, 60)); // a poll already under way ends
    const hidden = vi.mocked(api.getScreeningSummary).mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(vi.mocked(api.getScreeningSummary).mock.calls.length).toBe(hidden);
    await user.click(screen.getByRole("button", { name: "toggle tab" }));
    await waitFor(() =>
      expect(vi.mocked(api.getScreeningSummary).mock.calls.length).toBeGreaterThan(hidden),
    );
  });

  it("assigns a recruiter to the selected candidates", async () => {
    const user = userEvent.setup();
    vi.mocked(api.actOnApplications).mockResolvedValue([]);
    vi.mocked(jobsApi.getJobChoices).mockResolvedValue({
      departments: [],
      teams: [],
      interview_templates: [],
      people: [{ id: "u-9", name: "Meera Iyer" }],
    });
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage />);
    await user.click(await screen.findByRole("checkbox", { name: "Select Asha Rao" }));
    await user.click(screen.getByRole("button", { name: "Assign recruiter" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(await within(dialog).findByLabelText("Person"), "Meera Iyer");
    await user.click(within(dialog).getByRole("button", { name: "Assign" }));
    await waitFor(() =>
      expect(api.actOnApplications).toHaveBeenCalledWith("j-1", {
        application_ids: ["a-1"],
        action: "assign_recruiter",
        user_id: "u-9",
      }),
    );
  });

  it("says whether the results were screened blind", async () => {
    const view = renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage />);
    expect(await screen.findByText(/Screened blind: the AI did not see names/)).toBeInTheDocument();
    view.unmount();
    vi.mocked(api.listScreeningResults).mockResolvedValue({
      items: [ranked({}), ranked({ application_id: "a-2", blind: false })],
      next_cursor: null,
    });
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage />);
    expect(await screen.findByRole("status")).toHaveTextContent(/shown to the AI/);
    expect(screen.getByText("Names shown")).toBeInTheDocument();
    expect(screen.queryByText(/Screened blind: the AI did not see names/)).not.toBeInTheDocument();
  });

  it("says when a candidate's screening could not be loaded, not that there is none", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getApplicationScreening).mockRejectedValue(new Error("offline"));
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage={false} />);
    await user.click(await screen.findByRole("button", { name: /Asha Rao.*Explain the ranking/ }));
    const sheet = await screen.findByRole("dialog", { name: "Why Asha Rao ranks #1" });
    expect(await within(sheet).findByRole("alert")).toHaveTextContent(/couldn't be loaded/);
    expect(within(sheet).queryByText("Not screened yet.")).not.toBeInTheDocument();
  });

  it("shows what happened to a candidate in words", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getApplicationScreening).mockResolvedValue({
      application_id: "a-1",
      job_id: "j-1",
      stage: "review",
      rank: null,
      candidate: ranked({}).candidate,
      result: null,
      history: [
        {
          from_stage: "parsed",
          to_stage: "review",
          action: "screening_failed",
          reason: "Screening could not be completed: review this candidate by hand",
          score: null,
          rank: null,
          override: false,
          actor_id: null,
          created_at: "2026-10-05T00:00:00Z",
        },
      ],
    });
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage={false} />);
    await user.click(await screen.findByRole("button", { name: /Asha Rao.*Explain the ranking/ }));
    const sheet = await screen.findByRole("dialog", { name: "Why Asha Rao ranks #1" });
    expect(await within(sheet).findByText(/Screening could not be completed:/)).toBeInTheDocument();
    expect(within(sheet).queryByText(/screening_failed/)).not.toBeInTheDocument();
  });

  it("exports the ranking", async () => {
    const user = userEvent.setup();
    vi.mocked(api.exportRanking).mockResolvedValue(new Blob(["Rank,Candidate"]));
    renderAdmin(<RankingPanel jobId="j-1" jobReference="JOB-0001" canManage />);
    await user.click(await screen.findByRole("button", { name: "Download Excel" }));
    await waitFor(() => expect(api.exportRanking).toHaveBeenCalledWith("j-1", "xlsx"));
  });
});
