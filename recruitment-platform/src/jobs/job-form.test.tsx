import { ApiProblem } from "@hirevion/api-client";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetNavigation, router } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { JobForm } from "./job-form";
import { job } from "./test-data";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  createJob: vi.fn(),
  updateJob: vi.fn(),
  getJobChoices: vi.fn(),
  suggestSkills: vi.fn(),
}));

const CHOICES: api.JobChoices = {
  departments: [{ id: "d-eng", name: "Engineering" }],
  teams: [{ id: "t-platform", name: "Platform" }],
  interview_templates: [{ id: "tpl-1", name: "Backend screen" }],
  people: [
    { id: "u-asha", name: "Asha Rao" },
    { id: "u-ravi", name: "Ravi Kumar" },
  ],
};

beforeEach(() => {
  resetNavigation("/jobs/new");
  vi.mocked(api.getJobChoices).mockResolvedValue(CHOICES);
  vi.mocked(api.suggestSkills).mockResolvedValue([
    { id: "s-k8s", name: "Kubernetes", category: "devops" },
  ]);
});

describe("JobForm", () => {
  it("keeps showing a recruiter who is no longer offered, and sends them back unchanged", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateJob).mockResolvedValue(job());
    renderAdmin(
      <JobForm job={job({ recruiter_id: "u-left", recruiter_name: "Meera Iyer (left)" })} />,
    );
    const recruiter = await screen.findByLabelText("Recruiter");
    await waitFor(() => expect(recruiter).toHaveDisplayValue("Meera Iyer (left)"));
    await user.type(screen.getByLabelText("Location"), "Pune");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.updateJob).toHaveBeenCalled());
    const [, body] = vi.mocked(api.updateJob).mock.calls[0] ?? [];
    expect(body?.recruiter_id).toBe("u-left");
  });

  it("needs a title, then creates the job and opens it", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createJob).mockResolvedValue(job({ id: "j-new", reference: "JOB-0007" }));
    renderAdmin(<JobForm />);

    await user.click(screen.getByRole("button", { name: "Create job" }));
    expect(await screen.findByText("Enter the job title.")).toBeInTheDocument();
    expect(api.createJob).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Title"), "Platform Engineer");
    await screen.findByRole("option", { name: "Engineering" });
    await user.selectOptions(screen.getByLabelText("Department"), "d-eng");
    await user.type(screen.getByLabelText("Responsibilities"), "Run clusters{Enter}Mentor");
    await user.type(screen.getByLabelText("Add a skill"), "kube");
    await user.click(await screen.findByRole("button", { name: "Kubernetes" }));
    await user.selectOptions(screen.getByLabelText("Importance for Kubernetes"), "preferred");
    await user.click(screen.getByRole("button", { name: "Create job" }));

    await waitFor(() => expect(api.createJob).toHaveBeenCalled());
    const [body] = vi.mocked(api.createJob).mock.calls[0] ?? [];
    expect(body).toMatchObject({
      title: "Platform Engineer",
      department_id: "d-eng",
      responsibilities: ["Run clusters", "Mentor"],
      skills: [{ name: "Kubernetes", importance: "preferred", min_years: null }],
    });
    expect(router.push).toHaveBeenCalledWith("/jobs/j-new");
  });

  it("checks that ranges are in order", async () => {
    const user = userEvent.setup();
    renderAdmin(<JobForm />);
    await user.type(screen.getByLabelText("Title"), "Analyst");
    await user.type(screen.getByLabelText("Minimum experience (years)"), "8");
    await user.type(screen.getByLabelText("Maximum experience (years)"), "3");
    await user.click(screen.getByRole("button", { name: "Create job" }));
    expect(await screen.findByText("The maximum can't be below the minimum.")).toBeInTheDocument();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it("edits a job and shows the API's field errors", async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateJob).mockRejectedValueOnce(
      new ApiProblem({
        type: "about:blank",
        status: 422,
        code: "invalid-reference",
        title: "Choose a current one",
        errors: [{ detail: "Choose a current one", pointer: "#/team_id" }],
      }),
    );
    renderAdmin(<JobForm job={job({ responsibilities: ["Design APIs"] })} />);

    expect(screen.getByLabelText("Responsibilities")).toHaveValue("Design APIs");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Choose a current one")).toBeInTheDocument();
  });

  it("is read-only without the permission to edit", () => {
    renderAdmin(<JobForm job={job()} readOnly />);
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });
});
