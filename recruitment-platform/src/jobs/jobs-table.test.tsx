import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetNavigation, router } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { JobsTable } from "./jobs-table";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listJobs: vi.fn(),
  getJobChoices: vi.fn(),
}));

function summary(overrides: Partial<api.JobSummary>): api.JobSummary {
  return {
    id: "j-1",
    number: 42,
    reference: "JOB-0042",
    title: "Backend Engineer",
    status: "open",
    department_id: "d-eng",
    department_name: "Engineering",
    location: "Pune",
    work_model: "hybrid",
    employment_type: "full_time",
    recruiter_id: "u-asha",
    recruiter_name: "Asha Rao",
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  resetNavigation("/jobs");
  vi.mocked(api.getJobChoices).mockResolvedValue({
    departments: [{ id: "d-eng", name: "Engineering" }],
    teams: [],
    people: [],
  });
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      summary({}),
      summary({ id: "j-2", number: 7, reference: "JOB-0007", title: "Analyst", status: "draft" }),
    ],
    next_cursor: null,
  });
});

describe("JobsTable", () => {
  it("lists jobs with their reference, status and recruiter", async () => {
    renderAdmin(<JobsTable canCreate />);
    const link = await screen.findByRole("link", { name: /Backend Engineer/ });
    expect(link).toHaveAttribute("href", "/jobs/j-1");
    const row = link.closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText("JOB-0042")).toBeInTheDocument();
    expect(cells.getByText("Open")).toBeInTheDocument();
    expect(cells.getByText("Asha Rao")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New job" })).toHaveAttribute("href", "/jobs/new");
  });

  it("filters by the status tab and searches", async () => {
    resetNavigation("/jobs", "status=draft");
    const user = userEvent.setup();
    renderAdmin(<JobsTable canCreate={false} />);
    await waitFor(() =>
      expect(api.listJobs).toHaveBeenCalledWith(expect.objectContaining({ status: "draft" })),
    );
    expect(screen.queryByRole("link", { name: "New job" })).not.toBeInTheDocument();

    await user.type(screen.getByRole("searchbox"), "JOB-0007{Enter}");
    expect(router.replace).toHaveBeenCalledWith(expect.stringContaining("q=JOB-0007"), {
      scroll: false,
    });
  });
});
