import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dashboardQuery } from "@/dashboard/dashboard-figures";
import { getJobChoices } from "@/jobs/api";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as templatesApi from "./api";
import { AssignDialog } from "./assign-dialog";
import * as api from "./assigned-api";
import { InterviewPage } from "./interview-page";
import { InterviewsTable } from "./interviews-table";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./assigned-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./assigned-api")>()),
  listInterviews: vi.fn(),
  getInterview: vi.fn(),
  assignInterviews: vi.fn(),
  sendInvitation: vi.fn(),
  rescheduleInterview: vi.fn(),
  cancelInterview: vi.fn(),
  setInterviewReviewers: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listTemplates: vi.fn(),
}));
vi.mock("@/jobs/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/jobs/api")>()),
  getJobChoices: vi.fn(),
}));

function summary(overrides: Partial<api.InterviewSummary> = {}): api.InterviewSummary {
  return {
    id: "iv-1",
    reference: "IV-0001",
    status: "invited",
    candidate: { id: "c-1", name: "Asha Rao" },
    job_id: "j-1",
    job_title: "Backend Engineer",
    application_id: "a-1",
    template_id: "t-1",
    template_version: 1,
    starts_at: "2026-10-12T04:30:00Z",
    expires_at: "2026-10-13T18:29:00Z",
    timezone: "Asia/Kolkata",
    duration_minutes: 45,
    proctoring_level: "standard",
    third_eye: "optional",
    created_at: "2026-10-09T00:00:00Z",
    updated_at: "2026-10-09T00:00:00Z",
    ...overrides,
  };
}

function interview(overrides: Partial<api.Interview> = {}): api.Interview {
  return {
    ...summary(),
    candidate_email: "asha@example.test",
    template_name: "Backend screen",
    policy: {
      proctoring_level: "standard",
      checks: ["face", "focus"],
      third_eye: "optional",
      recording: { screen: true, camera: true, audio: true },
    },
    questions: [],
    reviewers: [],
    events: [
      {
        id: "e-1",
        action: "created",
        from_status: null,
        to_status: "scheduled",
        reason: null,
        actor_type: "user",
        actor_id: "u-1",
        details: {},
        created_at: "2026-10-09T00:00:00Z",
      },
    ],
    invitations: [],
    invited_at: null,
    started_at: null,
    completed_at: null,
    ended_at: null,
    cancel_reason: null,
    reschedule_count: 0,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  resetNavigation("/interviews");
});

describe("InterviewsTable", () => {
  it("lists a tab's interviews, each linking to its page", async () => {
    vi.mocked(api.listInterviews).mockResolvedValue({ items: [summary()], next_cursor: null });
    renderAdmin(<InterviewsTable statusGroup="upcoming" />);
    const link = await screen.findByRole("link", { name: "Open the interview with Asha Rao" });
    expect(link).toHaveAttribute("href", "/interviews/iv-1");
    expect(screen.getByText("Invited")).toBeInTheDocument();
    expect(api.listInterviews).toHaveBeenCalledWith(
      expect.objectContaining({ status_group: "upcoming" }),
    );
  });

  it("says when a tab is empty", async () => {
    vi.mocked(api.listInterviews).mockResolvedValue({ items: [], next_cursor: null });
    renderAdmin(<InterviewsTable statusGroup="live" />);
    expect(await screen.findByText("No interviews in progress")).toBeInTheDocument();
  });
});

describe("InterviewPage", () => {
  it("shows the pinned template, the window and the history", async () => {
    vi.mocked(api.getInterview).mockResolvedValue(interview({ status: "scheduled" }));
    renderAdmin(<InterviewPage id="iv-1" canManage />);
    expect(await screen.findByText("IV-0001: Asha Rao")).toBeInTheDocument();
    expect(screen.getByText("Backend screen, version 1")).toBeInTheDocument();
    expect(screen.getByText(/Fixed when the interview was created/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send invitation" })).toBeInTheDocument();
  });

  it("sends the invitation of a scheduled interview", async () => {
    vi.mocked(api.getInterview).mockResolvedValue(interview({ status: "scheduled" }));
    vi.mocked(api.sendInvitation).mockResolvedValue(interview({ status: "invited" }));
    renderAdmin(<InterviewPage id="iv-1" canManage />);
    await userEvent.click(await screen.findByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(api.sendInvitation).toHaveBeenCalledWith("iv-1"));
    expect(await screen.findByRole("button", { name: "Resend invitation" })).toBeInTheDocument();
  });

  it("cancels only with a reason", async () => {
    vi.mocked(api.getInterview).mockResolvedValue(interview());
    vi.mocked(api.cancelInterview).mockResolvedValue(
      interview({ status: "cancelled", cancel_reason: "Role filled" }),
    );
    renderAdmin(<InterviewPage id="iv-1" canManage />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel interview" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Cancel interview" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Role filled");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.cancelInterview).toHaveBeenCalledWith("iv-1", "Role filled"));
  });

  it("offers no changes to someone who can only view", async () => {
    vi.mocked(api.getInterview).mockResolvedValue(interview({ status: "scheduled" }));
    renderAdmin(<InterviewPage id="iv-1" canManage={false} />);
    await screen.findByText("IV-0001: Asha Rao");
    expect(screen.queryByRole("button", { name: "Send invitation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });

  it("chooses reviewers", async () => {
    vi.mocked(api.getInterview).mockResolvedValue(interview());
    vi.mocked(getJobChoices).mockResolvedValue({
      departments: [],
      teams: [],
      interview_templates: [],
      people: [{ id: "u-ravi", name: "Ravi Kumar" }],
    });
    vi.mocked(api.setInterviewReviewers).mockResolvedValue(
      interview({ reviewers: [{ id: "u-ravi", name: "Ravi Kumar" }] }),
    );
    renderAdmin(<InterviewPage id="iv-1" canManage />);
    await userEvent.click(await screen.findByRole("button", { name: "Change" }));
    await userEvent.click(await screen.findByLabelText("Ravi Kumar"));
    await userEvent.click(screen.getByRole("button", { name: "Save reviewers" }));
    await waitFor(() => expect(api.setInterviewReviewers).toHaveBeenCalledWith("iv-1", ["u-ravi"]));
  });
});

describe("AssignDialog", () => {
  it("creates the interviews and names the candidates it skipped", async () => {
    vi.mocked(templatesApi.listTemplates).mockResolvedValue({ items: [], next_cursor: null });
    vi.mocked(api.assignInterviews).mockResolvedValue({
      created: [summary()],
      skipped: [{ application_id: "a-2", code: "no-email", reason: "No email" }],
    });
    const onDone = vi.fn();
    renderAdmin(
      <AssignDialog
        applicationIds={["a-1", "a-2"]}
        names={{ "a-1": "Asha Rao", "a-2": "Kabir Shah" }}
        defaultTemplateId={null}
        onDone={onDone}
        onCancel={() => {}}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Create and invite" }));
    await waitFor(() =>
      expect(api.assignInterviews).toHaveBeenCalledWith(
        expect.objectContaining({
          application_ids: ["a-1", "a-2"],
          invite: true,
          template_id: null,
        }),
      ),
    );
    expect(
      await screen.findByText("Kabir Shah: has no email address to invite"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onDone).toHaveBeenCalled();
  });
});

describe("dashboardQuery", () => {
  it("turns the page's filters into the API's, days in the reader's time zone", () => {
    const query = dashboardQuery(
      new URLSearchParams("from=2026-10-01&to=2026-10-07&team=t1&candidateStatus=shortlisted"),
    );
    expect(query).toEqual({
      from: new Date("2026-10-01T00:00:00").toISOString(),
      to: new Date("2026-10-08T00:00:00").toISOString(),
      team: "t1",
    });
  });

  it("ignores a date that isn't one", () => {
    const query = dashboardQuery(new URLSearchParams("from=yesterday&to=2026-13-40"));
    expect(query).toEqual({ from: undefined, to: undefined });
  });
});
