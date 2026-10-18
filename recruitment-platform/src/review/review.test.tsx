import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as proctoring from "@/interviews/proctoring-api";
import * as session from "@/interviews/session-api";
import { renderAdmin, renderWithIntl } from "@/test/render";
import * as api from "./api";
import { HiringPanel } from "./hiring-panel";
import { EventsPanel, NotesPanel, TranscriptPanel } from "./panels";
import { PendingQueue } from "./pending-queue";
import { MediaPlayer } from "./player";
import { ScoresPanel } from "./scores-panel";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getHiringState: vi.fn(),
  changeHiringStatus: vi.fn(),
  addHiringInput: vi.fn(),
  getPendingReviews: vi.fn(),
  getScores: vi.fn(),
  changeScore: vi.fn(),
  listInterviewNotes: vi.fn(),
  addInterviewNote: vi.fn(),
  getProctoringEvents: vi.fn(),
}));
vi.mock("@/interviews/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/interviews/session-api")>()),
  getTranscript: vi.fn(),
}));
vi.mock("@/interviews/proctoring-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/interviews/proctoring-api")>()),
  reviewEvent: vi.fn(),
}));

const STATE: api.HiringState = {
  application_id: "app-1",
  candidate_id: "c-1",
  job_id: "j-1",
  job_title: "Backend Engineer",
  status: "interview_completed",
  allowed: ["under_review", "shortlisted", "additional_review", "selected", "rejected", "on_hold"],
  has_interview: true,
  decision: null,
  history: [
    {
      id: "h-1",
      from_status: "interview_started",
      to_status: "interview_completed",
      source: "system",
      decision: false,
      reason: null,
      actor_id: null,
      actor_name: null,
      interview_id: "iv-1",
      created_at: "2026-10-17T10:00:00Z",
    },
  ],
  inputs: [
    {
      id: "in-1",
      author_id: "u-2",
      author_name: "Hari Menon",
      interview_id: "iv-1",
      recommendation: "hire",
      ratings: { technical: 4 },
      rationale: "Fits the team.",
      created_at: "2026-10-17T11:00:00Z",
    },
  ],
};

beforeEach(() => {
  vi.mocked(api.getHiringState).mockResolvedValue(STATE);
});

describe("HiringPanel", () => {
  it("shows the status, the managers' input and the history", async () => {
    renderAdmin(<HiringPanel applicationId="app-1" canInput={false} />);
    expect(
      await screen.findByText("Interview completed", { selector: "span" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Hari Menon: Yes")).toBeInTheDocument();
    expect(screen.getByText("Technical 4/5")).toBeInTheDocument();
    expect(screen.getByText("Fits the team.")).toBeInTheDocument();
    expect(screen.queryByText("Give your recommendation")).not.toBeInTheDocument();
  });

  it("asks why for a decision, warns it is final, and moves the status", async () => {
    const user = userEvent.setup();
    vi.mocked(api.changeHiringStatus).mockResolvedValue({
      ...STATE,
      status: "selected",
      allowed: [],
      decision: {
        ...STATE.history[0],
        id: "h-2",
        to_status: "selected",
        decision: true,
        reason: "Strongest candidate.",
        actor_name: "Rita Rao",
        source: "user",
      } as api.HistoryItem,
    });
    renderAdmin(<HiringPanel applicationId="app-1" canInput={false} />);
    await user.click(await screen.findByRole("button", { name: "Change status" }));
    const dialog = await screen.findByRole("dialog", { name: "Change the hiring status" });
    await user.selectOptions(within(dialog).getByLabelText("Move to"), "selected");
    expect(within(dialog).getByRole("note")).toHaveTextContent("This is the final decision");
    const decide = within(dialog).getByRole("button", { name: "Make the decision" });
    expect(decide).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Why?"), "Strongest candidate.");
    await user.click(decide);
    await waitFor(() =>
      expect(api.changeHiringStatus).toHaveBeenCalledWith("app-1", {
        status: "selected",
        reason: "Strongest candidate.",
      }),
    );
    expect(await screen.findByText(/Selected by Rita Rao/)).toBeInTheDocument();
  });

  it("offers nothing to move to when the reader can't", async () => {
    vi.mocked(api.getHiringState).mockResolvedValue({ ...STATE, allowed: [] });
    renderAdmin(<HiringPanel applicationId="app-1" canInput={false} />);
    await screen.findByText("Hari Menon: Yes");
    expect(screen.queryByRole("button", { name: "Change status" })).not.toBeInTheDocument();
  });

  it("takes a hiring manager's recommendation with its reasons", async () => {
    const user = userEvent.setup();
    vi.mocked(api.addHiringInput).mockResolvedValue(STATE.inputs[0] as api.HiringInput);
    renderAdmin(<HiringPanel applicationId="app-1" canInput />);
    await user.selectOptions(await screen.findByLabelText("Recommendation"), "strong_hire");
    await user.selectOptions(screen.getByLabelText("Technical"), "5");
    const save = screen.getByRole("button", { name: "Save recommendation" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Your reasons"), "Great depth.");
    await user.click(save);
    await waitFor(() =>
      expect(api.addHiringInput).toHaveBeenCalledWith("app-1", {
        recommendation: "strong_hire",
        ratings: { technical: 5 },
        rationale: "Great depth.",
      }),
    );
  });
});

describe("PendingQueue", () => {
  it("lists interviews waiting for a decision with what needs a look", async () => {
    vi.mocked(api.getPendingReviews).mockResolvedValue({
      total: 1,
      items: [
        {
          interview_id: "iv-1",
          reference: "IV-0001",
          application_id: "app-1",
          candidate_id: "c-1",
          candidate_name: "Asha Rao",
          job_title: "Backend Engineer",
          hiring_status: "interview_completed",
          completed_at: "2026-10-17T10:00:00Z",
          overall_score: 7.44,
          evaluated: true,
          unreviewed_critical: 2,
        },
      ],
    });
    renderAdmin(<PendingQueue />);
    expect(await screen.findByText("1 interview waits for a decision.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review Asha Rao" })).toHaveAttribute(
      "href",
      "/interviews/iv-1/review",
    );
    expect(screen.getByText("7.4")).toBeInTheDocument();
    expect(screen.getByText("2 critical events not reviewed")).toBeInTheDocument();
  });

  it("says when nothing is waiting", async () => {
    vi.mocked(api.getPendingReviews).mockResolvedValue({ total: 0, items: [] });
    renderAdmin(<PendingQueue />);
    expect(await screen.findByText("Nothing is waiting for review")).toBeInTheDocument();
  });
});

const SCORE = (ai: number | null, value: number | null, reason?: string): api.ScoreValue => ({
  ai,
  value,
  change: reason
    ? {
        id: "c",
        scope: "communication",
        target: null,
        previous_score: ai,
        new_score: value ?? 0,
        reason,
        changed_by: "u-1",
        changed_by_name: "Rita Rao",
        created_at: "2026-10-17T10:00:00Z",
      }
    : null,
});
const SCORES: api.Scores = {
  interview_id: "iv-1",
  evaluation_id: "ev-1",
  overall: SCORE(6.1, 6.1),
  communication: SCORE(5.8, 6.5, "Clear but slow."),
  skills: { PostgreSQL: SCORE(8.6, 8.6), Python: SCORE(2.5, 2.5) },
  questions: {},
  changes: [],
};

describe("ScoresPanel", () => {
  it("shows the AI's score beside the one in force, with who changed it and why", async () => {
    vi.mocked(api.getScores).mockResolvedValue(SCORES);
    renderAdmin(<ScoresPanel id="iv-1" canModify={false} />);
    const row = (await screen.findByRole("row", { name: /Communication/ })) as HTMLElement;
    expect(within(row).getByText("5.8")).toBeInTheDocument();
    expect(within(row).getByText("6.5")).toBeInTheDocument();
    expect(within(row).getByText("Rita Rao: Clear but slow.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change a score" })).not.toBeInTheDocument();
  });

  it("changes a score with a reason", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getScores).mockResolvedValue(SCORES);
    vi.mocked(api.changeScore).mockResolvedValue(SCORES);
    renderAdmin(<ScoresPanel id="iv-1" canModify />);
    await user.click(await screen.findByRole("button", { name: "Change a score" }));
    const dialog = await screen.findByRole("dialog", { name: "Change a score" });
    await user.selectOptions(within(dialog).getByLabelText("What"), "skill:Python");
    const save = within(dialog).getByRole("button", { name: "Save change" });
    await user.type(within(dialog).getByLabelText("New score (0 to 10)"), "11");
    await user.type(within(dialog).getByLabelText("Why?"), "Saw the code.");
    expect(save).toBeDisabled(); // out of range
    await user.clear(within(dialog).getByLabelText("New score (0 to 10)"));
    await user.type(within(dialog).getByLabelText("New score (0 to 10)"), "7.5");
    await user.click(save);
    await waitFor(() =>
      expect(api.changeScore).toHaveBeenCalledWith("iv-1", {
        scope: "skill",
        target: "Python",
        new_score: 7.5,
        reason: "Saw the code.",
      }),
    );
  });

  it("says the evaluation isn't ready", async () => {
    vi.mocked(api.getScores).mockRejectedValue(
      Object.assign(new Error("x"), { name: "ApiProblem", status: 409, code: "not-evaluated" }),
    );
    renderAdmin(<ScoresPanel id="iv-1" canModify />);
    expect(await screen.findByText(/no scores yet|couldn't be loaded/)).toBeInTheDocument();
  });
});

const SEGMENTS = [
  {
    seq: 1,
    speaker: "ai",
    text: "Please introduce yourself.",
    start_ms: 0,
    end_ms: 4000,
    question_id: null,
    confidence: null,
  },
  {
    seq: 2,
    speaker: "candidate",
    text: "I build Python services.",
    start_ms: 5000,
    end_ms: 9000,
    question_id: null,
    confidence: null,
  },
] as session.TranscriptSegment[];

describe("TranscriptPanel", () => {
  it("marks the line being played and jumps to a line", async () => {
    const user = userEvent.setup();
    const jump = vi.fn();
    vi.mocked(session.getTranscript).mockResolvedValue({
      segments: SEGMENTS,
    } as session.Transcript);
    renderAdmin(<TranscriptPanel id="iv-1" offset={6_000} onJump={jump} />);
    const current = await screen.findByRole("button", { name: "Jump to 0:05, Candidate" });
    expect(current).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Jump to 0:00, AI" })).not.toHaveAttribute(
      "aria-current",
    );
    await user.click(screen.getByRole("button", { name: "Jump to 0:00, AI" }));
    expect(jump).toHaveBeenCalledWith(0);
  });
});

const ANCHOR = "2026-10-17T10:00:00.000Z";
const EVENT = (over: Partial<proctoring.ProctorEvent>): proctoring.ProctorEvent =>
  ({
    id: "e-1",
    seq: 1,
    event: "PHONE_DETECTED",
    source: "camera",
    origin: "client",
    severity: "CRITICAL",
    started_at: "2026-10-17T10:02:30.000Z",
    duration_ms: 2000,
    ongoing: false,
    phase: null,
    confidence: 0.9,
    details: {},
    review_status: "pending",
    policy_version: 1,
    evidence_count: 1,
    review: null,
    ...over,
  }) as proctoring.ProctorEvent;

describe("EventsPanel", () => {
  it("jumps to an event's moment and reviews it with a reason", async () => {
    const user = userEvent.setup();
    const jump = vi.fn();
    vi.mocked(api.getProctoringEvents).mockResolvedValue({
      events: [
        EVENT({}),
        EVENT({
          id: "e-2",
          event: "GAZE_DEVIATION",
          severity: "WARNING",
          started_at: "2026-10-17T10:00:40.000Z",
          review_status: "false_positive",
          review: {
            outcome: "false_positive",
            reason: "A second monitor.",
            reviewer_id: "u",
            reviewed_at: ANCHOR,
          },
        }),
      ],
      next_cursor: null,
    } as unknown as api.ProctoringEvents);
    vi.mocked(proctoring.reviewEvent).mockResolvedValue(EVENT({ review_status: "confirmed" }));
    renderAdmin(<EventsPanel id="iv-1" anchor={ANCHOR} canReview onJump={jump} />);
    await user.click(await screen.findByRole("button", { name: "Jump to Phone detected at 2:30" }));
    expect(jump).toHaveBeenCalledWith(150_000);
    // A dismissed event stays, marked, with its reason.
    expect(screen.getByText("False positive")).toBeInTheDocument();
    const [reviewPhone] = screen.getAllByRole("button", { name: "Review" });
    await user.click(reviewPhone as HTMLElement);
    await user.type(screen.getByLabelText("Why?"), "Clearly a phone.");
    await user.click(screen.getByRole("button", { name: "Save review" }));
    await waitFor(() =>
      expect(proctoring.reviewEvent).toHaveBeenCalledWith(
        "iv-1",
        "e-1",
        "confirmed",
        "Clearly a phone.",
      ),
    );
  });

  it("shows events without a review button to someone who can't review", async () => {
    vi.mocked(api.getProctoringEvents).mockResolvedValue({
      events: [EVENT({})],
      next_cursor: null,
    } as unknown as api.ProctoringEvents);
    renderAdmin(<EventsPanel id="iv-1" anchor={ANCHOR} canReview={false} onJump={vi.fn()} />);
    await screen.findByText("Phone detected");
    expect(screen.queryByRole("button", { name: "Review" })).not.toBeInTheDocument();
  });
});

describe("NotesPanel", () => {
  it("adds a note at the moment being watched, or without one", async () => {
    const user = userEvent.setup();
    vi.mocked(api.listInterviewNotes).mockResolvedValue([]);
    vi.mocked(api.addInterviewNote).mockResolvedValue({} as api.Note);
    renderAdmin(<NotesPanel id="iv-1" offset={62_000} />);
    await user.type(await screen.findByLabelText("Add a note"), "Hesitated here.");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() =>
      expect(api.addInterviewNote).toHaveBeenLastCalledWith("iv-1", {
        body: "Hesitated here.",
        at_ms: 62_000,
      }),
    );
    await user.click(screen.getByLabelText("Note the moment (1:02)"));
    await user.type(screen.getByLabelText("Add a note"), "In general: strong.");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() =>
      expect(api.addInterviewNote).toHaveBeenLastCalledWith("iv-1", {
        body: "In general: strong.",
        at_ms: null,
      }),
    );
  });
});

const TRACKS = (url: string | null): api.ReviewMedia => ({
  interview_id: "iv-1",
  anchor: ANCHOR,
  expires_at: "2026-10-17T11:00:00Z",
  tracks: [
    {
      track: "camera",
      kind: "camera",
      label: "Camera",
      status: url ? "assembled" : "assembly-pending",
      stalled: false,
      url,
      container: url ? "webm" : null,
      duration_ms: url ? 60_000 : null,
      started_at: ANCHOR,
      timeline: null,
      gaps: [],
    },
    {
      track: "screen-1",
      kind: "screen",
      label: "Screen 1",
      status: url ? "assembled" : "assembly-pending",
      stalled: false,
      url,
      container: url ? "mp4" : null,
      duration_ms: url ? 20_000 : null,
      started_at: ANCHOR,
      timeline: null,
      gaps: [],
    },
  ],
});

describe("MediaPlayer", () => {
  beforeEach(() => {
    // jsdom has no media playback.
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    HTMLMediaElement.prototype.pause = vi.fn();
  });

  it("says when the recordings aren't ready, and when there are none", () => {
    const view = renderWithIntl(
      <MediaPlayer
        media={TRACKS(null)}
        offset={0}
        playing={false}
        seekRevision={0}
        end={0}
        onOffset={vi.fn()}
        onSeek={vi.fn()}
        onPlayingChange={vi.fn()}
        onExpired={vi.fn()}
      />,
    );
    expect(screen.getByText(/still being prepared/)).toBeInTheDocument();
    view.unmount();
    renderWithIntl(
      <MediaPlayer
        media={{ ...TRACKS(null), tracks: [] }}
        offset={0}
        playing={false}
        seekRevision={0}
        end={0}
        onOffset={vi.fn()}
        onSeek={vi.fn()}
        onPlayingChange={vi.fn()}
        onExpired={vi.fn()}
      />,
    );
    expect(screen.getByText("This interview has no recordings.")).toBeInTheDocument();
  });

  it("puts every track on the one clock: dragging seeks, the screen rests where it has nothing", () => {
    const onSeek = vi.fn();
    const onPlayingChange = vi.fn();
    renderWithIntl(
      <MediaPlayer
        media={TRACKS("https://files.test/x")}
        offset={30_000}
        playing={false}
        seekRevision={1}
        end={60_000}
        onOffset={vi.fn()}
        onSeek={onSeek}
        onPlayingChange={onPlayingChange}
        onExpired={vi.fn()}
      />,
    );
    const camera = screen.getByLabelText("Camera") as HTMLVideoElement;
    expect(camera.currentTime).toBe(30);
    // The screen's file is only 20 s long: nothing is recorded at 30 s.
    expect(
      within(document.querySelector('[data-track="screen-1"]') as HTMLElement).getByText(
        "Nothing recorded here",
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider", { name: "Position in the interview" }), {
      target: { value: "45000" },
    });
    expect(onSeek).toHaveBeenCalledWith(45_000);
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuetext", "0:30 of 1:00");
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(onPlayingChange).toHaveBeenCalledWith(true);
  });
});
