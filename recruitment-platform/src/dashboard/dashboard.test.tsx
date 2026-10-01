import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { resetNavigation, router } from "@/test/navigation";
import { renderWithIntl } from "@/test/render";
import { DashboardFilters } from "./dashboard-filters";
import { KpiGrid } from "./kpi-grid";
import { PipelineBoard } from "./pipeline-board";

describe("KpiGrid", () => {
  it("shows the ten PRD §10 figures, with no data where a module hasn't landed", () => {
    renderWithIntl(<KpiGrid values={{ openJobs: 1234567 }} />);
    const terms = screen.getAllByRole("term").map((term) => term.textContent);
    expect(terms).toEqual([
      "Open jobs",
      "Active candidates",
      "Screened",
      "Shortlisted",
      "Interviews scheduled",
      "Live interviews",
      "Completed interviews",
      "Pending reviews",
      "Proctoring alerts",
      "In the hiring pipeline",
    ]);
    expect(screen.getByText("12,34,567")).toBeInTheDocument();
    expect(screen.getAllByText("no data yet")).toHaveLength(9);
  });
});

describe("DashboardFilters", () => {
  it("keeps the filters in the URL", () => {
    resetNavigation("/dashboard", "team=t1");
    renderWithIntl(<DashboardFilters />);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
    expect(router.replace).toHaveBeenLastCalledWith("/dashboard?team=t1&from=2026-10-01", {
      scroll: false,
    });
  });

  it("offers all seven filters", () => {
    resetNavigation("/dashboard");
    renderWithIntl(<DashboardFilters />);
    for (const name of [
      "From",
      "To",
      "Recruiter",
      "Team",
      "Job",
      "Department",
      "Candidate status",
      "Interview status",
    ]) {
      expect(screen.getByLabelText(name), name).toBeInTheDocument();
    }
  });

  it("clears every filter at once", async () => {
    const user = userEvent.setup();
    resetNavigation("/dashboard", "candidateStatus=shortlisted&from=2026-10-01");
    renderWithIntl(<DashboardFilters />);
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(router.replace).toHaveBeenLastCalledWith("/dashboard", { scroll: false });
  });
});

describe("PipelineBoard", () => {
  it("has a column for each PRD §72 status, in order", () => {
    renderWithIntl(<PipelineBoard columns={{}} />);
    const board = screen.getByRole("region", { name: "Hiring pipeline" });
    const headings = within(board)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual([
      "Under review",
      "Shortlisted",
      "Interview invited",
      "Interview started",
      "Interview completed",
      "Additional review",
      "Selected",
      "Rejected",
      "On hold",
    ]);
  });

  it("lists a column's candidates with its count, and says when it's empty", () => {
    renderWithIntl(
      <PipelineBoard
        columns={{ shortlisted: [{ id: "a1", name: "Asha Rao", job: "Backend engineer" }] }}
      />,
    );
    const column = screen.getByRole("region", { name: "Shortlisted" });
    expect(within(column).getByText("Asha Rao")).toBeInTheDocument();
    expect(within(column).getByText("1")).toBeInTheDocument();
    const empty = screen.getByRole("region", { name: "Selected" });
    expect(within(empty).getByText("No candidates")).toBeInTheDocument();
    expect(column).toHaveAttribute("tabindex", "0");
  });
});
