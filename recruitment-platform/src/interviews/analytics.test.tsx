import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderAdmin } from "@/test/render";
import * as api from "./analytics-api";
import { InterviewAnalyticsPanel } from "./analytics-panel";
import * as gate from "./use-evaluation-gate";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./analytics-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./analytics-api")>()),
  getInterviewAnalytics: vi.fn(),
}));
vi.mock("./use-evaluation-gate", () => ({ useEvaluationGate: vi.fn() }));

const question = (position: number, fields: Partial<api.AnalyticsQuestion>) => ({
  id: `q-${position}`,
  position,
  kind: "main",
  skill: "Redis",
  difficulty: "easy",
  text: `Question ${position} about Redis?`,
  status: "answered",
  asked_ms: position * 60_000,
  thinking_ms: 4_000,
  speaking_ms: 20_000,
  words: 50,
  quality: "partial",
  score: 6.5,
  ...fields,
});

const ANALYTICS: api.InterviewAnalytics = {
  interview_id: "iv-1",
  status: "evaluated",
  planned_minutes: 30,
  started_at: "2026-11-21T10:17:05Z",
  ended_at: "2026-11-21T10:29:45Z",
  duration_ms: 760_000,
  overall: 7.2,
  communication: 6.8,
  questions: [
    question(0, { kind: "introduction", skill: null, difficulty: null, score: null }),
    question(1, { score: 8.1 }),
    question(2, { status: "skipped", score: null }),
  ],
  skills: [
    {
      skill: "Redis",
      required: true,
      covered: true,
      asked: 2,
      answered: 1,
      planned: 2,
      dropped: false,
      score: 7.5,
    },
    {
      skill: "Kafka",
      required: false,
      covered: false,
      asked: 0,
      answered: 0,
      planned: 1,
      dropped: false,
      score: null,
    },
  ],
  speech: {
    candidate_ms: 120_000,
    ai_ms: 180_000,
    words: 300,
    words_per_minute: 150,
    median_response_ms: 4_000,
    long_pauses: 1,
    fillers: { um: 3 },
    fillers_per_100_words: 1,
    candidate_share: 0.4,
    pace_unreliable: false,
  },
  integrity: {
    counts: { INFO: 1, WARNING: 0, CRITICAL: 2 },
    events: [
      {
        id: "e-1",
        event: "PROCESS_INVENTORY",
        severity: "INFO",
        source: "native",
        offset_ms: 1_000,
        duration_ms: null,
        review: null,
      },
      {
        id: "e-2",
        event: "PHONE_DETECTED",
        severity: "CRITICAL",
        source: "third_eye",
        offset_ms: 300_000,
        duration_ms: 2_000,
        review: "confirmed",
      },
      {
        id: "e-3",
        event: "BLOCKED_PROCESS_DETECTED",
        severity: "CRITICAL",
        source: "native",
        offset_ms: 10_000,
        duration_ms: null,
        review: null,
      },
    ],
    inventory: {
      offset_ms: 1_000,
      count: 3,
      windows: ["chrome.exe"],
      processes: [
        {
          name: "chrome.exe",
          path: "C:\\c.exe",
          publisher: "Google LLC",
          window_titles: ["Inbox"],
        },
        { name: "svchost.exe", path: "C:\\s.exe", publisher: null, window_titles: [] },
        { name: "svchost.exe", path: "C:\\s.exe", publisher: null, window_titles: [] },
      ],
    },
  },
};

function revealed(value: boolean, loaded = true) {
  vi.mocked(gate.useEvaluationGate).mockReturnValue({
    revealed: value,
    loaded,
    failed: false,
    progress: { saved: 1, total: 3 },
    waive: vi.fn(),
  });
}

beforeEach(() => {
  vi.mocked(api.getInterviewAnalytics).mockResolvedValue(ANALYTICS);
  revealed(true);
});

describe("InterviewAnalyticsPanel", () => {
  it("shows the scores per skill and per question once the reviewer may see them", async () => {
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    expect(await screen.findByText("Score per skill")).toBeInTheDocument();
    expect(screen.getByText("7.2 / 10")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Redis: 7.5 out of 10" })).toBeInTheDocument();
    expect(screen.getByText("Not covered")).toBeInTheDocument();
    // Answered questions only: the skipped one has no column.
    expect(screen.getByRole("button", { name: "Question 1: 8.1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Question 2:/ })).not.toBeInTheDocument();
  });

  it("keeps the AI's numbers hidden until the reviewer has scored, and offers to skip", async () => {
    revealed(false);
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    expect(await screen.findByText(/1 of 3 scored/)).toBeInTheDocument();
    expect(screen.queryByText("7.2 / 10")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Redis: 7.5 out of 10" })).not.toBeInTheDocument();
    expect(screen.getByText("Hidden until you've scored every question.")).toBeInTheDocument();
    // What isn't a score shows: speech and timing.
    expect(screen.getByText("150 words a minute")).toBeInTheDocument();
  });

  it("draws the proctoring events on the timeline and groups the processes", async () => {
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    const phone = await screen.findByRole("button", {
      name: "Phone detected · 5 min 0 s · confirmed by a reviewer",
    });
    expect(phone).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Apps running when monitoring started/ }),
    ).toBeNull();
    expect(
      screen.getByText("3 processes were running when monitoring started"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByText("Show every process"));
    const table = screen.getByRole("table", { name: "Processes running when monitoring started" });
    expect(within(table).getByText("svchost.exe ×2")).toBeInTheDocument();
    expect(within(table).getByText("Google LLC")).toBeInTheDocument();
  });

  it("says when the stored speech times can't give a pace", async () => {
    vi.mocked(api.getInterviewAnalytics).mockResolvedValue({
      ...ANALYTICS,
      speech: { ...ANALYTICS.speech, words_per_minute: null, pace_unreliable: true },
    });
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    expect(await screen.findByText("Not measured")).toBeInTheDocument();
    expect(screen.getByText(/too short to give a pace/)).toBeInTheDocument();
  });

  it("leaves out the integrity part for a reader who may not see proctoring", async () => {
    vi.mocked(api.getInterviewAnalytics).mockResolvedValue({ ...ANALYTICS, integrity: null });
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    expect(await screen.findByText("Score per skill")).toBeInTheDocument();
    expect(screen.queryByText("Integrity")).not.toBeInTheDocument();
  });

  it("names the question a column stands for when it is hovered or focused", async () => {
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    const column = await screen.findByRole("button", { name: "Question 1: 8.1" });
    await userEvent.hover(column);
    const detail = screen.getByRole("status", { name: "Question details" });
    expect(within(detail).getByText("Question 1 about Redis?")).toBeInTheDocument();
  });

  it("shows neither the scores nor the skip button while the reviewer's scores load", async () => {
    revealed(false, false);
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    expect(await screen.findByText("Score per skill")).toBeInTheDocument();
    expect(screen.queryByText("7.2 / 10")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show the scores without scoring" })).toBeNull();
  });

  it("places the events along the planned length when the interview has no end", async () => {
    vi.mocked(api.getInterviewAnalytics).mockResolvedValue({
      ...ANALYTICS,
      ended_at: null,
      duration_ms: null,
    });
    renderAdmin(<InterviewAnalyticsPanel interviewId="iv-1" />);
    expect(
      await screen.findByRole("button", {
        name: "Phone detected · 5 min 0 s · confirmed by a reviewer",
      }),
    ).toBeInTheDocument();
  });
});
