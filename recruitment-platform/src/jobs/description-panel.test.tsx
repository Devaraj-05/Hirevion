import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { DescriptionPanel } from "./description-panel";
import { job } from "./test-data";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getDescription: vi.fn(),
  submitDescription: vi.fn(),
  applyDescription: vi.fn(),
  retryDocument: vi.fn(),
}));

function description(overrides: Partial<api.JobDescription> = {}): api.JobDescription {
  return {
    id: "doc-1",
    status: "parsed",
    filename: null,
    content_type: "text/plain",
    size: 120,
    error_code: null,
    attempts: 1,
    created_at: "2026-10-02T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    text: "Senior Python Engineer",
    flags: {},
    extraction: {
      title: "Senior Python Engineer",
      required_skills: [
        { name: "Python", skill_id: "s-py", quote: "5+ years of Python" },
        { name: "Kubernetes", skill_id: "s-k8s", quote: "Experience with Kubernetes" },
      ],
      preferred_skills: [{ name: "Go", skill_id: "s-go", quote: "Go" }],
      experience_min: 5,
      experience_max: null,
      responsibilities: [{ text: "Design APIs", quote: "Design APIs" }],
      qualifications: [],
      domain: [],
      location: null,
      work_model: "remote",
      dropped: 1,
      sections: ["requirements"],
      model: "mock",
    },
    ...overrides,
  };
}

beforeEach(() => {
  resetNavigation("/jobs/j-1");
});

describe("DescriptionPanel", () => {
  it("polls while the description is read, and stops once it is", async () => {
    vi.mocked(api.getDescription)
      .mockResolvedValueOnce(description({ status: "scanning", extraction: null }))
      .mockResolvedValue(description());
    renderAdmin(<DescriptionPanel job={job()} canEdit pollMs={20} />);

    expect(await screen.findByText("Checking for viruses")).toBeInTheDocument();
    expect(await screen.findByText("Review what was found")).toBeInTheDocument();
    const calls = vi.mocked(api.getDescription).mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(vi.mocked(api.getDescription).mock.calls.length).toBe(calls);
  });

  it("shows where each skill was found, and what was left out", async () => {
    vi.mocked(api.getDescription).mockResolvedValue(description());
    renderAdmin(<DescriptionPanel job={job()} canEdit />);
    expect(
      await screen.findByText("From the description: “5+ years of Python”"),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 item was left out/)).toBeInTheDocument();
  });

  it("applies the reviewed fields, keeping the job's own skills", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDescription).mockResolvedValue(description());
    vi.mocked(api.applyDescription).mockResolvedValue(job());
    renderAdmin(
      <DescriptionPanel
        job={job({
          skills: [{ name: "SQL", skill_id: null, importance: "optional", min_years: null }],
        })}
        canEdit
      />,
    );

    await user.click(await screen.findByRole("checkbox", { name: "Kubernetes" }));
    const responsibilities = screen.getByLabelText("Responsibilities");
    await user.type(responsibilities, "{End}{Enter}Mentor engineers");
    await user.click(screen.getByRole("button", { name: "Apply to job" }));

    await waitFor(() => expect(api.applyDescription).toHaveBeenCalled());
    const [jobId, body] = vi.mocked(api.applyDescription).mock.calls[0] ?? [];
    expect(jobId).toBe("j-1");
    expect(body).toMatchObject({
      document_id: "doc-1",
      title: "Senior Python Engineer",
      experience_min: 5,
      work_model: "remote",
      responsibilities: ["Design APIs", "Mentor engineers"],
      skills: [
        { name: "SQL", importance: "optional", min_years: null },
        { name: "Python", importance: "required", min_years: null },
        { name: "Go", importance: "preferred", min_years: null },
      ],
    });
  });

  it("offers Retry when reading failed", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDescription).mockResolvedValue(
      description({ status: "failed", error_code: "unreadable", extraction: null }),
    );
    vi.mocked(api.retryDocument).mockResolvedValue(description({ status: "uploaded" }));
    renderAdmin(<DescriptionPanel job={job()} canEdit />);

    expect(await screen.findByText(/the file couldn't be opened/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(api.retryDocument).toHaveBeenCalledWith("doc-1"));
  });

  it("says when the description could not be loaded, rather than offering to replace it", async () => {
    vi.mocked(api.getDescription).mockRejectedValue(new Error("offline"));
    renderAdmin(<DescriptionPanel job={job()} canEdit />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't be loaded/);
    expect(screen.queryByRole("button", { name: "Read description" })).not.toBeInTheDocument();
  });

  it("goes back to the current description from Replace", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDescription).mockResolvedValue(description());
    renderAdmin(<DescriptionPanel job={job()} canEdit />);
    await user.click(await screen.findByRole("button", { name: "Send a new description" }));
    expect(screen.queryByText("Review what was found")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep the current description" }));
    expect(await screen.findByText("Review what was found")).toBeInTheDocument();
  });

  it("tells a reader who cannot edit that there is no description, without telling them to send one", async () => {
    vi.mocked(api.getDescription).mockResolvedValue(null);
    renderAdmin(<DescriptionPanel job={job()} canEdit={false} />);
    expect(await screen.findByText("This job has no description yet.")).toBeInTheDocument();
    expect(screen.queryByText(/Paste the job description or upload/)).not.toBeInTheDocument();
  });

  it("links a multi-word skill to the words it was found in", async () => {
    const found = description();
    found.extraction = {
      ...(found.extraction as object),
      required_skills: [{ name: "Machine Learning", skill_id: null, quote: "ML models in prod" }],
      preferred_skills: [],
    } as typeof found.extraction;
    vi.mocked(api.getDescription).mockResolvedValue(found);
    renderAdmin(<DescriptionPanel job={job()} canEdit />);
    const box = await screen.findByRole("checkbox", { name: "Machine Learning" });
    const described = box.getAttribute("aria-describedby") ?? "";
    expect(described).not.toMatch(/\s/);
    expect(document.getElementById(described)).toHaveTextContent("ML models in prod");
  });

  it("lets the reviewer change a skill from preferred to required, and warns of a cut-off description", async () => {
    const user = userEvent.setup();
    const found = description();
    found.extraction = {
      ...(found.extraction as object),
      truncated: true,
    } as typeof found.extraction;
    vi.mocked(api.getDescription).mockResolvedValue(found);
    vi.mocked(api.applyDescription).mockResolvedValue(job());
    renderAdmin(<DescriptionPanel job={job()} canEdit />);
    expect(await screen.findByText(/only its first part was read/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Go: treat as"), "Required");
    await user.click(screen.getByRole("button", { name: "Apply to job" }));
    await waitFor(() => expect(api.applyDescription).toHaveBeenCalled());
    const [, body] = vi.mocked(api.applyDescription).mock.calls[0] ?? [];
    expect(body?.skills).toContainEqual({ name: "Go", importance: "required", min_years: null });
  });

  it("sends a pasted description", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getDescription).mockResolvedValue(null);
    vi.mocked(api.submitDescription).mockResolvedValue(description({ status: "uploaded" }));
    renderAdmin(<DescriptionPanel job={job()} canEdit />);

    await user.click(await screen.findByRole("button", { name: "Read description" }));
    expect(await screen.findByText("Paste the job description.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Job description"), "We need a Go developer.");
    await user.click(screen.getByRole("button", { name: "Read description" }));
    await waitFor(() =>
      expect(api.submitDescription).toHaveBeenCalledWith(
        "j-1",
        { text: "We need a Go developer." },
        expect.any(String),
      ),
    );
  });
});
