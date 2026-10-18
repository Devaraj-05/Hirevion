import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { CandidatePage } from "./candidate-page";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getCandidate: vi.fn(),
}));

const CANDIDATE: api.Candidate = {
  id: "c-1",
  name: "Asha Rao",
  email: "asha.rao@example.test",
  phone: "9876543210",
  location: "Pune",
  headline: "Senior Engineer at Acme Software",
  skills: ["Python"],
  flags: { injection: ["ignore previous instructions"], possible_duplicate_of: "c-9" },
  created_at: "2026-10-03T00:00:00Z",
  updated_at: "2026-10-03T00:00:00Z",
  profile: {
    name: { value: "Asha Rao", quote: "Asha Rao", page: 1, section: null },
    email: {
      value: "asha.rao@example.test",
      quote: "asha.rao@example.test",
      page: 1,
      section: null,
    },
    phone: null,
    location: { value: "Pune", quote: "Pune", page: 1, section: null },
    summary: null,
    total_experience_years: 6,
    skills: [{ name: "Python", years: 5, quote: "5 years of Python", page: 1, section: "skills" }],
    positions: [
      {
        company: "Acme Software",
        title: "Senior Engineer",
        start: "2020",
        end: null,
        current: true,
        quote: "Senior Engineer, Acme Software",
        page: 2,
        section: "experience",
      },
    ],
    education: [],
    certifications: [],
    projects: [],
    achievements: [],
    languages: [],
    links: [{ url: "javascript:alert(1)", quote: "my site", page: 1, section: null }],
  },
  skill_details: [{ name: "Python", skill_id: "s-py", years: 5 }],
  applications: [
    {
      id: "a-1",
      job_id: "j-1",
      job_reference: "JOB-0001",
      job_title: "Backend Engineer",
      stage: "parsed",
      hiring_status: "under_review",
      created_at: "2026-10-03T00:00:00Z",
    },
  ],
  documents: [
    {
      id: "doc-1",
      filename: "asha.pdf",
      content_type: "application/pdf",
      size: 1200,
      status: "parsed",
      flags: {},
      created_at: "2026-10-03T00:00:00Z",
    },
  ],
};

beforeEach(() => {
  resetNavigation("/candidates/c-1");
  vi.mocked(api.getCandidate).mockResolvedValue(CANDIDATE);
});

describe("CandidatePage", () => {
  it("shows each item with where in the resume it came from", async () => {
    renderAdmin(<CandidatePage id="c-1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Asha Rao" })).toBeInTheDocument();
    expect(
      screen.getByText("From the resume, page 2: “Senior Engineer, Acme Software”"),
    ).toBeInTheDocument();
    expect(screen.getByText("From the resume, page 1: “5 years of Python”")).toBeInTheDocument();
    expect(screen.getByText("6 years of experience")).toBeInTheDocument();
  });

  it("shows the flags to check, and never links unsafe URLs", async () => {
    renderAdmin(<CandidatePage id="c-1" />);
    const warnings = await screen.findByRole("region", { name: "Things to check" });
    expect(
      within(warnings).getByText(/Contains instructions aimed at AI screening/),
    ).toBeInTheDocument();
    expect(within(warnings).getByText(/May be a duplicate/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "javascript:alert(1)" })).not.toBeInTheDocument();
  });

  it("lists the resumes with downloads, and the applications", async () => {
    const user = userEvent.setup();
    renderAdmin(<CandidatePage id="c-1" />);
    await user.click(await screen.findByRole("tab", { name: "Resumes" }));
    expect(screen.getByRole("link", { name: "Download asha.pdf" })).toHaveAttribute(
      "href",
      "/api/v1/documents/doc-1/download",
    );
    await user.click(screen.getByRole("tab", { name: "Applications" }));
    expect(screen.getByRole("link", { name: /JOB-0001/ })).toHaveAttribute("href", "/jobs/j-1");
  });
});
