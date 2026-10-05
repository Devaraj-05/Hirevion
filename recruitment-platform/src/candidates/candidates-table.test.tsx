import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as jobsApi from "@/jobs/api";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { CandidatesTable } from "./candidates-table";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listCandidates: vi.fn(),
}));
vi.mock("@/jobs/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/jobs/api")>()),
  listJobs: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(jobsApi.listJobs).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(api.listCandidates).mockResolvedValue({
    items: [
      {
        id: "c-1",
        name: "Asha Rao",
        email: "asha.rao@example.test",
        location: "Pune",
        headline: "Senior Engineer at Acme Software",
        skills: ["Python", "Kubernetes"],
        flags: {},
        created_at: "2026-10-03T00:00:00Z",
        updated_at: "2026-10-03T00:00:00Z",
      },
    ],
    next_cursor: null,
  });
});

describe("CandidatesTable", () => {
  it("lists candidates linking to their pages, filtered by the URL", async () => {
    resetNavigation("/candidates", "q=asha&job=j-1");
    renderAdmin(<CandidatesTable />);
    expect(await screen.findByRole("link", { name: /Asha Rao/ })).toHaveAttribute(
      "href",
      "/candidates/c-1",
    );
    expect(screen.getByText("Python, Kubernetes")).toBeInTheDocument();
    await waitFor(() =>
      expect(api.listCandidates).toHaveBeenCalledWith(
        expect.objectContaining({ q: "asha", job_id: "j-1" }),
      ),
    );
  });

  it("filters by the stage tab, and explains the tabs interviews will fill", async () => {
    resetNavigation("/candidates", "stage=shortlisted");
    const first = renderAdmin(<CandidatesTable />);
    await waitFor(() =>
      expect(api.listCandidates).toHaveBeenCalledWith(
        expect.objectContaining({ stage_group: "shortlisted" }),
      ),
    );
    first.unmount();

    vi.mocked(api.listCandidates).mockClear();
    resetNavigation("/candidates", "stage=interview");
    renderAdmin(<CandidatesTable />);
    expect(await screen.findByText(/once interviews arrive/)).toBeInTheDocument();
    expect(api.listCandidates).not.toHaveBeenCalled();
  });
});
