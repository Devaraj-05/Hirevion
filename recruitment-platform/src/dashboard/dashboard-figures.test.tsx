import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/interviews/assigned-api";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import { DashboardFigures } from "./dashboard-figures";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/interviews/assigned-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/interviews/assigned-api")>()),
  getDashboard: vi.fn(),
}));

const FIGURES: Awaited<ReturnType<typeof api.getDashboard>> = {
  open_jobs: 4,
  active_candidates: 31,
  screened: 22,
  shortlisted: 7,
  in_pipeline: 36,
  interviews_scheduled: 5,
  live_interviews: 1,
  completed_interviews: 9,
  pending_reviews: 3,
  proctoring_alerts: 12,
};

function tile(name: string): HTMLElement {
  const label = screen.getByText(name);
  return label.closest("dl") as HTMLElement;
}

beforeEach(() => {
  resetNavigation("/dashboard");
  vi.mocked(api.getDashboard).mockReset();
});

describe("DashboardFigures", () => {
  it("shows every §10 figure from the API", async () => {
    vi.mocked(api.getDashboard).mockResolvedValue(FIGURES);
    renderAdmin(<DashboardFigures live />);
    expect(await within(tile("Open jobs")).findByText("4")).toBeInTheDocument();
    for (const [name, value] of [
      ["Active candidates", "31"],
      ["Screened", "22"],
      ["Shortlisted", "7"],
      ["In the hiring pipeline", "36"],
      ["Interviews scheduled", "5"],
      ["Live interviews", "1"],
      ["Completed interviews", "9"],
      ["Pending reviews", "3"],
      ["Proctoring alerts", "12"],
    ] as const) {
      expect(within(tile(name)).getByText(value), name).toBeInTheDocument();
    }
    expect(screen.queryByText("no data yet")).not.toBeInTheDocument();
  });

  it("shows 'no data yet' for what the reader may not read, and passes every filter on", async () => {
    resetNavigation(
      "/dashboard",
      "from=2026-10-01&recruiter=u1&team=t1&job=j1&department=d1&candidateStatus=shortlisted&interviewStatus=invited",
    );
    vi.mocked(api.getDashboard).mockResolvedValue({
      ...FIGURES,
      open_jobs: null,
      active_candidates: null,
      screened: null,
      shortlisted: null,
      in_pipeline: null,
      proctoring_alerts: null,
    });
    renderAdmin(<DashboardFigures live />);
    expect(await within(tile("Pending reviews")).findByText("3")).toBeInTheDocument();
    expect(within(tile("Open jobs")).getByText("no data yet")).toBeInTheDocument();
    expect(api.getDashboard).toHaveBeenCalledWith(
      expect.objectContaining({
        recruiter: "u1",
        team: "t1",
        job: "j1",
        department: "d1",
        candidateStatus: "shortlisted",
        interviewStatus: "invited",
      }),
    );
  });

  it("says when the figures could not be loaded, not that there is no data", async () => {
    vi.mocked(api.getDashboard).mockRejectedValue(new Error("offline"));
    renderAdmin(<DashboardFigures live />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't be loaded/);
  });

  it("asks nothing of a development session that has no account behind it", () => {
    renderAdmin(<DashboardFigures live={false} />);
    expect(api.getDashboard).not.toHaveBeenCalled();
    expect(within(tile("Open jobs")).getByText("no data yet")).toBeInTheDocument();
  });
});
