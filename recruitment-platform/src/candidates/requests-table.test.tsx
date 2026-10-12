import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderAdmin } from "@/test/render";
import {
  type CandidateRequest,
  listCandidateRequests,
  updateCandidateRequest,
} from "./requests-api";
import { CandidateRequestsTable } from "./requests-table";

vi.mock("./requests-api", async (original) => ({
  ...(await original<typeof import("./requests-api")>()),
  listCandidateRequests: vi.fn(),
  updateCandidateRequest: vi.fn(),
}));

const REQUEST: CandidateRequest = {
  id: "rq-1",
  reference: "RQ-1A2B3C4D",
  kind: "reschedule",
  status: "open",
  message: "I'm travelling that week",
  details: { preferred: "After the 20th" },
  response: null,
  candidate_id: "c-1",
  candidate_name: "Asha Rao",
  candidate_email: "asha@example.test",
  interview_id: "iv-1",
  interview_reference: "IV-0042",
  handled_by: null,
  handled_at: null,
  created_at: "2026-10-12T05:00:00Z",
  updated_at: "2026-10-12T05:00:00Z",
};

beforeEach(() => {
  vi.mocked(listCandidateRequests).mockReset();
  vi.mocked(updateCandidateRequest).mockReset();
  vi.mocked(listCandidateRequests).mockResolvedValue({ items: [REQUEST], next_cursor: null });
});

describe("CandidateRequestsTable", () => {
  it("lists requests with the candidate, the kind and the interview", async () => {
    renderAdmin(<CandidateRequestsTable canManage />);
    const row = (await screen.findByText("RQ-1A2B3C4D")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Asha Rao")).toBeVisible();
    expect(within(row).getByText("Reschedule an interview")).toBeVisible();
    expect(within(row).getByRole("link", { name: "IV-0042" })).toHaveAttribute(
      "href",
      "/interviews/iv-1",
    );
    expect(within(row).getByText("Received")).toBeVisible();
  });

  it("filters by status", async () => {
    const user = userEvent.setup();
    renderAdmin(<CandidateRequestsTable canManage />);
    await screen.findByText("RQ-1A2B3C4D");
    await user.selectOptions(screen.getByLabelText("Status"), "open");
    expect(listCandidateRequests).toHaveBeenLastCalledWith("open", null);
  });

  it("records a reply and a new status", async () => {
    vi.mocked(updateCandidateRequest).mockResolvedValue({ ...REQUEST, status: "resolved" });
    const user = userEvent.setup();
    renderAdmin(<CandidateRequestsTable canManage />);
    await user.click(await screen.findByRole("button", { name: "Update RQ-1A2B3C4D" }));
    const dialog = screen.getByRole("dialog", { name: "Update the request" });
    expect(within(dialog).getByText("I'm travelling that week")).toBeVisible();
    expect(within(dialog).getByText("After the 20th")).toBeVisible();
    await user.selectOptions(within(dialog).getByLabelText("New status"), "resolved");
    await user.type(within(dialog).getByLabelText("Reply to the candidate"), "Moved to the 22nd");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(updateCandidateRequest).toHaveBeenCalledWith("rq-1", {
      status: "resolved",
      response: "Moved to the 22nd",
    });
  });

  it("offers no update without the permission", async () => {
    renderAdmin(<CandidateRequestsTable canManage={false} />);
    await screen.findByText("RQ-1A2B3C4D");
    expect(screen.queryByRole("button", { name: /Update/ })).toBeNull();
  });
});
