import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderAdmin } from "@/test/render";
import * as api from "./evaluation-api";
import { EvaluationCard } from "./evaluation-card";
import { DIMENSIONS } from "./evaluation-model";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./evaluation-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./evaluation-api")>()),
  getEvaluation: vi.fn(),
  getQuestionEvaluation: vi.fn(),
  listMyScores: vi.fn(),
  saveMyScores: vi.fn(),
  getCalibration: vi.fn(),
  queueRerun: vi.fn(),
}));

const EVIDENCE = {
  quote: "run EXPLAIN ANALYZE to see the real plan",
  seq: 12,
  start_ms: 83_000,
  end_ms: 91_000,
  question_id: "q-1",
};
const STATEMENT = { summary: "", evidence: [], supported: false };
const SCORES = Object.fromEntries(DIMENSIONS.map((d) => [d, 8]));

const BODY: api.EvaluationBody = {
  id: "ev-1",
  sequence: 1,
  versions: {
    prompt: "evaluation-question-v1",
    synthesis_prompt: "evaluation-synthesis-v1",
    rubric: "dimensions-v1+w36137962",
    evaluation: "evaluation-v1",
    model: "mock-llm",
    models: ["mock-llm"],
  },
  rubric_weights: Object.fromEntries(DIMENSIONS.map((d) => [d, 12])),
  created_at: "2026-10-12T05:00:00Z",
  completed_at: "2026-10-12T05:01:00Z",
  overall_score: 7.4,
  communication: { score: 8.1, evidence: [EVIDENCE], supported: true, summary: STATEMENT },
  skills: [
    {
      skill: "PostgreSQL",
      weight: 60,
      required: true,
      score: 8.2,
      questions: 2,
      dimensions: SCORES,
      evidence: [EVIDENCE],
      supported: true,
    },
    {
      skill: "Python",
      weight: 40,
      required: false,
      score: 4.5,
      questions: 1,
      dimensions: SCORES,
      evidence: [],
      supported: false,
    },
  ],
  strengths: [
    { text: "Reads query plans.", skill: "PostgreSQL", evidence: [EVIDENCE], supported: true },
  ],
  knowledge_gaps: [
    { text: "Never mentions statistics.", skill: null, evidence: [], supported: false },
  ],
  follow_up_performance: { asked: 1, mean: 6, main_mean: 8, delta: -2, summary: STATEMENT },
  coding: { status: "pending", score: null, source: "sp-16" },
  flags: ["manipulation_attempt"],
  questions: [
    {
      question_id: "q-1",
      position: 2,
      kind: "main",
      skill: "PostgreSQL",
      text: "How do you find out why a query is slow?",
      weight: 1,
      overall_score: 8.2,
      scores: SCORES,
      unsupported: [],
      flags: [],
    },
  ],
};

const READY: api.EvaluationResponse = {
  interview_id: "iv-1",
  interview_status: "evaluated",
  state: "ready",
  evaluation: BODY,
};

const DETAIL: api.QuestionEvaluation = {
  question_id: "q-1",
  position: 2,
  kind: "main",
  skill: "PostgreSQL",
  text: "How do you find out why a query is slow?",
  weight: 1,
  overall_score: 8.2,
  scores: SCORES,
  unsupported: ["evidence"],
  flags: [],
  dimensions: DIMENSIONS.map((dimension) => ({
    dimension,
    weight: 12,
    score: dimension === "evidence" ? 5 : 8,
    raw_score: dimension === "evidence" ? 9 : 8,
    supported: dimension !== "evidence",
    evidence: dimension === "evidence" ? [] : [EVIDENCE],
    rationale: "",
  })),
  missing_concepts: ["statistics"],
  note: "Names the plan but not the statistics.",
  model: "mock-llm",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listMyScores).mockResolvedValue([]);
});

describe("EvaluationCard", () => {
  it("shows the scores with their verified quotes, and flags what has none", async () => {
    vi.mocked(api.getEvaluation).mockResolvedValue(READY);
    renderAdmin(<EvaluationCard id="iv-1" canRerun={false} canMeasure={false} />);
    // The AI's numbers stay back until the reviewer has scored, or chooses not to.
    expect(
      await screen.findByText(/hidden until you've scored every question/),
    ).toBeInTheDocument();
    expect(screen.getByText(/0 of 1 scored/)).toBeInTheDocument();
    expect(screen.queryByText("7.4")).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "Show the evaluation without scoring" }),
    );
    expect(await screen.findByText("7.4")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("8.2")).toBeInTheDocument();
    expect(screen.getByText("Evidence verified")).toBeInTheDocument();
    expect(screen.getByText("No verified evidence")).toBeInTheDocument();
    expect(
      screen.getAllByText(/“run EXPLAIN ANALYZE to see the real plan”/).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("1:23").length).toBeGreaterThan(0);
    expect(screen.getByText("Reads query plans.")).toBeInTheDocument();
    expect(screen.getByText("Never mentions statistics.")).toBeInTheDocument();
    expect(
      screen.getByText("1 follow-up averaged 6.0 against 8.0 on the main questions."),
    ).toBeInTheDocument();
    expect(screen.getByText("Flags for review: manipulation_attempt")).toBeInTheDocument();
    expect(
      screen.getByText(/Scored by mock-llm with prompt evaluation-question-v1/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Repeat with pinned versions" })).toBeNull();
  });

  it("says when the interview isn't evaluated yet", async () => {
    vi.mocked(api.getEvaluation).mockResolvedValue({
      interview_id: "iv-1",
      interview_status: "evaluating",
      state: "evaluating",
      evaluation: null,
    });
    renderAdmin(<EvaluationCard id="iv-1" canRerun canMeasure={false} />);
    expect(await screen.findByText(/is being evaluated/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Repeat with pinned versions" })).toBeNull();
  });

  it("keeps the AI's scores back until the reviewer has saved their own", async () => {
    vi.mocked(api.getEvaluation).mockResolvedValue(READY);
    vi.mocked(api.getQuestionEvaluation).mockResolvedValue(DETAIL);
    vi.mocked(api.saveMyScores).mockResolvedValue({
      question_id: "q-1",
      dimensions: { correctness: 7, evidence: 9 },
      note: "",
      updated_at: "2026-10-12T06:00:00Z",
    });
    renderAdmin(<EvaluationCard id="iv-1" canRerun={false} canMeasure={false} />);
    await userEvent.click(await screen.findByText("How do you find out why a query is slow?"));
    expect(screen.getByText(/Score the answer yourself first/)).toBeInTheDocument();
    expect(api.getQuestionEvaluation).not.toHaveBeenCalled();
    const save = screen.getByRole("button", { name: "Save my scores" });
    expect(save).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Correctness"), "11");
    expect(screen.getByText("Scores run from 0 to 10.")).toBeInTheDocument();
    expect(save).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("Correctness"));
    await userEvent.type(screen.getByLabelText("Correctness"), "7");
    await userEvent.type(screen.getByLabelText("Evidence"), "9");
    expect(save).toBeEnabled();

    vi.mocked(api.listMyScores).mockResolvedValue([
      {
        question_id: "q-1",
        dimensions: { correctness: 7, evidence: 9 },
        note: "",
        updated_at: "2026-10-12T06:00:00Z",
      },
    ]);
    await userEvent.click(save);
    await waitFor(() =>
      expect(api.saveMyScores).toHaveBeenCalledWith(
        "iv-1",
        "q-1",
        { correctness: 7, evidence: 9 },
        "",
      ),
    );
    const table = await screen.findByRole("table");
    const correctness = within(table).getByText("Correctness").closest("tr");
    expect(correctness).not.toBeNull();
    // You 7.0, the AI 8.0, the AI minus you +1.
    expect(within(correctness as HTMLElement).getByText("7.0")).toBeInTheDocument();
    expect(within(correctness as HTMLElement).getByText("8.0")).toBeInTheDocument();
    expect(within(correctness as HTMLElement).getByText("+1")).toBeInTheDocument();
    const evidence = within(table).getByText("Evidence").closest("tr") as HTMLElement;
    expect(
      within(evidence).getByText("Capped at 5: no quote could be verified."),
    ).toBeInTheDocument();
    expect(screen.getByText("Missed: statistics")).toBeInTheDocument();
  });

  it("lets an admin repeat the evaluation, and says what was queued", async () => {
    vi.mocked(api.getEvaluation).mockResolvedValue(READY);
    vi.mocked(api.queueRerun).mockResolvedValue({ action: "rerun" });
    renderAdmin(<EvaluationCard id="iv-1" canRerun canMeasure={false} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Repeat with pinned versions" }),
    );
    await waitFor(() => expect(api.queueRerun).toHaveBeenCalledWith("iv-1"));
    // Queued: a second press would only queue it again.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Repeat with pinned versions" })).toBeDisabled(),
    );
  });

  it("starts from the scores already saved and keeps the ones it doesn't change", async () => {
    vi.mocked(api.getEvaluation).mockResolvedValue(READY);
    vi.mocked(api.getQuestionEvaluation).mockResolvedValue(DETAIL);
    vi.mocked(api.listMyScores).mockResolvedValue([
      {
        question_id: "q-1",
        dimensions: { correctness: 7, clarity: 6, evidence: 9 },
        note: "earlier",
        updated_at: "2026-10-12T06:00:00Z",
      },
    ]);
    vi.mocked(api.saveMyScores).mockResolvedValue({
      question_id: "q-1",
      dimensions: { correctness: 7, clarity: 8, evidence: 9 },
      note: "earlier",
      updated_at: "2026-10-12T06:05:00Z",
    });
    renderAdmin(<EvaluationCard id="iv-1" canRerun={false} canMeasure={false} />);
    await userEvent.click(await screen.findByText("How do you find out why a query is slow?"));
    expect(screen.getByLabelText("Correctness")).toHaveValue("7");
    expect(screen.getByLabelText("Note")).toHaveValue("earlier");
    await userEvent.clear(screen.getByLabelText("Clarity"));
    await userEvent.type(screen.getByLabelText("Clarity"), "8");
    // Clearing a dimension must not drop it from what is saved either.
    await userEvent.clear(screen.getByLabelText("Evidence"));
    await userEvent.click(screen.getByRole("button", { name: "Save my scores" }));
    await waitFor(() =>
      expect(api.saveMyScores).toHaveBeenCalledWith(
        "iv-1",
        "q-1",
        { correctness: 7, clarity: 8, evidence: 9 },
        "earlier",
      ),
    );
  });

  it("keeps checking for an evaluation that hasn't appeared yet", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(api.getEvaluation)
        .mockResolvedValueOnce({
          interview_id: "iv-1",
          interview_status: "completed",
          state: "none",
          evaluation: null,
        })
        .mockResolvedValue(READY);
      renderAdmin(<EvaluationCard id="iv-1" canRerun={false} canMeasure={false} />);
      expect(
        await screen.findByText("The interview hasn't been evaluated yet."),
      ).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(5500);
      expect(
        await screen.findByText(/hidden until you've scored every question/),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers a retry for an evaluation that gave up", async () => {
    vi.mocked(api.getEvaluation).mockResolvedValue({
      interview_id: "iv-1",
      interview_status: "completed",
      state: "failed",
      evaluation: null,
    });
    vi.mocked(api.queueRerun).mockResolvedValue({ action: "evaluate" });
    renderAdmin(<EvaluationCard id="iv-1" canRerun canMeasure={false} />);
    expect(await screen.findByText("The evaluation couldn't be completed.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry the evaluation" }));
    await waitFor(() => expect(api.queueRerun).toHaveBeenCalledWith("iv-1"));
  });

  it("words the organisation's agreement with the reviewers", async () => {
    vi.mocked(api.getEvaluation).mockResolvedValue(READY);
    const stats = {
      n: 40,
      spearman: 0.81,
      weighted_kappa: 0.72,
      mean_abs_diff: 0.9,
      within_one: 0.75,
    };
    vi.mocked(api.getCalibration).mockResolvedValue({
      pairs: 40,
      questions: 6,
      reviewers: 3,
      overall: stats,
      by_dimension: {},
      bias: 0.35,
    });
    renderAdmin(<EvaluationCard id="iv-1" canRerun={false} canMeasure />);
    expect(await screen.findByText("Moderate agreement")).toBeInTheDocument();
    expect(screen.getByText("0.72")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("+0.35")).toBeInTheDocument();
    expect(screen.getByText(/40 scores from 3 reviewers on 6 questions/)).toBeInTheDocument();
  });
});
