import { ApiProblem } from "@hirevion/api-client";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { JobPage } from "./job-page";
import { job } from "./test-data";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getJob: vi.fn(),
  setJobStatus: vi.fn(),
  listJobVersions: vi.fn(),
  getJobChoices: vi.fn(),
  getDescription: vi.fn(),
}));

beforeEach(() => {
  resetNavigation("/jobs/j-1");
  vi.mocked(api.getJobChoices).mockResolvedValue({ departments: [], teams: [], people: [] });
  vi.mocked(api.getDescription).mockResolvedValue(null);
  vi.mocked(api.listJobVersions).mockResolvedValue([
    {
      version: 1,
      reason: "created",
      created_by: null,
      created_at: "2026-10-02T00:00:00Z",
      snapshot: {},
    },
    {
      version: 2,
      reason: "jd-applied",
      created_by: null,
      created_at: "2026-10-02T01:00:00Z",
      snapshot: {},
    },
  ]);
});

describe("JobPage", () => {
  it("shows the job and only the status moves allowed from its status", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getJob).mockResolvedValue(job({ status: "open" }));
    vi.mocked(api.setJobStatus).mockResolvedValue(job({ status: "paused" }));
    renderAdmin(<JobPage id="j-1" canEdit />);

    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeInTheDocument();
    expect(screen.getByText("JOB-0001")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open job" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(api.setJobStatus).toHaveBeenCalledWith("j-1", "paused"));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("explains what an incomplete job needs before it can open", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getJob).mockResolvedValue(job({ status: "draft" }));
    vi.mocked(api.setJobStatus).mockRejectedValue(
      new ApiProblem({
        type: "about:blank",
        status: 422,
        code: "job-incomplete",
        title: "Add what an open job needs first",
        detail: "description, required skills",
      }),
    );
    renderAdmin(<JobPage id="j-1" canEdit />);
    await user.click(await screen.findByRole("button", { name: "Open job" }));
    expect(
      await screen.findByText(/give it a title, a description and at least one required skill/),
    ).toBeInTheDocument();
  });

  it("offers no status moves to someone who can only view", async () => {
    vi.mocked(api.getJob).mockResolvedValue(job({ status: "open" }));
    renderAdmin(<JobPage id="j-1" canEdit={false} />);
    await screen.findByRole("heading", { name: "Backend Engineer" });
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("lists the job's versions", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getJob).mockResolvedValue(job());
    renderAdmin(<JobPage id="j-1" canEdit />);
    await user.click(await screen.findByRole("tab", { name: "History" }));
    expect(await screen.findByText("Description applied")).toBeInTheDocument();
  });
});
