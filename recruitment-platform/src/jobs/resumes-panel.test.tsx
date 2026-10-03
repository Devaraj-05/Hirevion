import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as candidatesApi from "@/candidates/api";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as jobsApi from "./api";
import { ResumesPanel } from "./resumes-panel";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/candidates/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/candidates/api")>()),
  uploadResume: vi.fn(),
  listResumes: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  retryDocument: vi.fn(),
}));

function resume(overrides: Partial<candidatesApi.ResumeDocument>): candidatesApi.ResumeDocument {
  return {
    id: "doc-1",
    kind: "resume",
    status: "parsed",
    filename: "asha.pdf",
    content_type: "application/pdf",
    size: 1200,
    error_code: null,
    attempts: 1,
    parent_id: null,
    flags: {},
    candidate: { id: "c-1", name: "Asha Rao" },
    created_at: "2026-10-03T00:00:00Z",
    updated_at: "2026-10-03T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  resetNavigation("/jobs/j-1");
  vi.mocked(candidatesApi.uploadResume).mockReset();
  vi.mocked(candidatesApi.listResumes).mockReset();
});

describe("ResumesPanel", () => {
  it("sends each file in its own request with its own key", async () => {
    const user = userEvent.setup();
    vi.mocked(candidatesApi.listResumes).mockResolvedValue({ items: [], next_cursor: null });
    vi.mocked(candidatesApi.uploadResume).mockResolvedValue(resume({ status: "uploaded" }));
    renderAdmin(<ResumesPanel jobId="j-1" canUpload />);

    await user.upload(screen.getByLabelText("Choose files"), [
      new File(["Asha"], "asha.pdf", { type: "application/pdf" }),
      new File(["Ravi"], "ravi.txt", { type: "text/plain" }),
    ]);
    await waitFor(() => expect(candidatesApi.uploadResume).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(candidatesApi.uploadResume).mock.calls;
    expect(calls.map(([job, file]) => [job, file.name])).toEqual([
      ["j-1", "asha.pdf"],
      ["j-1", "ravi.txt"],
    ]);
    expect(new Set(calls.map(([, , key]) => key)).size).toBe(2);
    expect(await screen.findAllByText("Sent")).toHaveLength(2);
  });

  it("polls while anything is unfinished, and stops once all is final", async () => {
    vi.mocked(candidatesApi.listResumes)
      .mockResolvedValueOnce({
        items: [resume({ status: "parsing", candidate: null })],
        next_cursor: null,
      })
      .mockResolvedValue({ items: [resume({})], next_cursor: null });
    renderAdmin(<ResumesPanel jobId="j-1" canUpload pollMs={20} />);

    expect(await screen.findByText("Reading the resume")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Asha Rao" })).toHaveAttribute(
      "href",
      "/candidates/c-1",
    );
    const calls = vi.mocked(candidatesApi.listResumes).mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(vi.mocked(candidatesApi.listResumes).mock.calls.length).toBe(calls);
  });

  it("offers Retry for a failed resume and shows flags", async () => {
    const user = userEvent.setup();
    vi.mocked(candidatesApi.listResumes).mockResolvedValue({
      items: [
        resume({ id: "doc-2", status: "failed", error_code: "unreadable", candidate: null }),
        resume({ flags: { injection: ["ignore previous instructions"] } }),
      ],
      next_cursor: null,
    });
    vi.mocked(jobsApi.retryDocument).mockResolvedValue({
      id: "doc-2",
      status: "uploaded",
      filename: "asha.pdf",
      content_type: "application/pdf",
      size: 1200,
      error_code: null,
      attempts: 1,
      created_at: "2026-10-03T00:00:00Z",
      updated_at: "2026-10-03T00:00:00Z",
    });
    renderAdmin(<ResumesPanel jobId="j-1" canUpload />);

    expect(
      await screen.findByText("Contains instructions aimed at AI screening"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try asha.pdf again" }));
    await waitFor(() => expect(jobsApi.retryDocument).toHaveBeenCalledWith("doc-2"));
  });

  it("lets someone without the permission look but not upload", async () => {
    vi.mocked(candidatesApi.listResumes).mockResolvedValue({ items: [], next_cursor: null });
    renderAdmin(<ResumesPanel jobId="j-1" canUpload={false} />);
    expect(await screen.findByText(/uploading them needs/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose files")).not.toBeInTheDocument();
  });
});
