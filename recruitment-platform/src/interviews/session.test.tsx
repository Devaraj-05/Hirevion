import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InterviewBriefingCard } from "@/admin/organization/interview-briefing-card";
import { renderAdmin } from "@/test/render";
import { AccommodationsCard } from "./accommodations-card";
import * as api from "./session-api";
import { TranscriptCard } from "./transcript-card";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./session-api")>()),
  getTranscript: vi.fn(),
  listAccommodations: vi.fn(),
  decideAccommodation: vi.fn(),
  getInterviewBriefing: vi.fn(),
  saveInterviewBriefing: vi.fn(),
}));

const TRANSCRIPT: api.Transcript = {
  interview_id: "iv-1",
  status: "completed",
  stage: "evaluation",
  transcript_status: "ready",
  coverage: [
    { skill: "PostgreSQL", required: true, covered: true, asked: 2, answered: 2, planned: 2 },
    { skill: "Redis", required: false, covered: false, asked: 0, answered: 0, planned: 1 },
  ],
  questions: [
    {
      id: "q-1",
      position: 1,
      kind: "main",
      stage: "medium",
      skill: "PostgreSQL",
      difficulty: "medium",
      type: "resume_based",
      text: "Your resume mentions the project Ledger service. What role did PostgreSQL play?",
      source: "resume",
      source_ref: { field: "projects", quote: "Moved reporting queries to read replicas", page: 1 },
      parent_id: null,
      status: "answered",
      asked_at: "2026-10-12T05:00:00Z",
      answers: [],
    },
  ],
  segments: [
    {
      seq: 1,
      speaker: "ai",
      text: "Your resume mentions the project Ledger service. What role did PostgreSQL play?",
      start_ms: 65_000,
      end_ms: 70_000,
      question_id: "q-1",
      confidence: null,
    },
    {
      seq: 2,
      speaker: "candidate",
      text: "We moved the reporting reads to replicas.",
      start_ms: 71_000,
      end_ms: 75_000,
      question_id: "q-1",
      confidence: 0.92,
    },
  ],
  artifacts: [{ kind: "vtt", url: "https://blob.example/t.vtt", bytes: 120, sha256: "ab" }],
};

const REQUEST: api.Accommodation = {
  id: "acc-1",
  kinds: ["text_answers", "extended_time"],
  note: "I have RSI",
  status: "requested",
  approved_kinds: [],
  decision_note: null,
  decided_by: null,
  decided_at: null,
  created_at: "2026-10-10T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TranscriptCard", () => {
  it("shows coverage, both speakers, the question's source and the files", async () => {
    vi.mocked(api.getTranscript).mockResolvedValue(TRANSCRIPT);
    renderAdmin(<TranscriptCard id="iv-1" live={false} />);
    expect(
      await screen.findByText("We moved the reporting reads to replicas."),
    ).toBeInTheDocument();
    expect(screen.getByText("Covered")).toBeInTheDocument();
    expect(screen.getByText("Not covered")).toBeInTheDocument();
    expect(screen.getByText("01:05")).toBeInTheDocument();
    expect(
      screen.getByText("From the resume, page 1: “Moved reporting queries to read replicas”"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download captions (VTT)" })).toHaveAttribute(
      "href",
      "https://blob.example/t.vtt",
    );
  });
});

describe("AccommodationsCard", () => {
  it("approves what the recruiter ticks", async () => {
    vi.mocked(api.listAccommodations).mockResolvedValue([REQUEST]);
    vi.mocked(api.decideAccommodation).mockResolvedValue({
      ...REQUEST,
      status: "approved",
      approved_kinds: ["text_answers"],
    });
    renderAdmin(<AccommodationsCard id="iv-1" canDecide />);
    await userEvent.click(await screen.findByLabelText("Extended time"));
    await userEvent.click(screen.getByRole("button", { name: "Approve selected" }));
    await waitFor(() =>
      expect(api.decideAccommodation).toHaveBeenCalledWith("iv-1", "acc-1", ["text_answers"], null),
    );
  });

  it("declines, and offers no decision to someone who can't make one", async () => {
    vi.mocked(api.listAccommodations).mockResolvedValue([REQUEST]);
    vi.mocked(api.decideAccommodation).mockResolvedValue({ ...REQUEST, status: "declined" });
    const { unmount } = renderAdmin(<AccommodationsCard id="iv-1" canDecide />);
    await userEvent.click(await screen.findByRole("button", { name: "Decline" }));
    await waitFor(() =>
      expect(api.decideAccommodation).toHaveBeenCalledWith("iv-1", "acc-1", [], null),
    );
    unmount();
    renderAdmin(<AccommodationsCard id="iv-1" canDecide={false} />);
    expect(await screen.findByText("The candidate wrote: I have RSI")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
  });
});

describe("InterviewBriefingCard", () => {
  it("saves the instructions line by line and the FAQ", async () => {
    vi.mocked(api.getInterviewBriefing).mockResolvedValue({ instructions: [], faq: [] });
    vi.mocked(api.saveInterviewBriefing).mockImplementation(async (body) => body);
    renderAdmin(<InterviewBriefingCard />);
    const instructions = await screen.findByLabelText("Instructions for candidates");
    await userEvent.type(instructions, "Join from a quiet room{enter}{enter}Keep your camera on");
    await userEvent.click(screen.getByRole("button", { name: "Add a question" }));
    await userEvent.type(screen.getByLabelText("Question 1"), "Is the role remote?");
    await userEvent.type(screen.getByLabelText("Answer"), "It is hybrid.");
    await userEvent.click(screen.getByRole("button", { name: "Save briefing" }));
    await waitFor(() =>
      expect(api.saveInterviewBriefing).toHaveBeenCalledWith({
        instructions: ["Join from a quiet room", "Keep your camera on"],
        faq: [{ question: "Is the role remote?", answer: "It is hybrid." }],
      }),
    );
  });
});
