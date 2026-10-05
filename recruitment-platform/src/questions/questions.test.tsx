import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listCandidates } from "@/candidates/api";
import { listTemplates } from "@/interviews/api";
import { listJobs } from "@/jobs/api";
import { resetNavigation, router } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { QuestionLibrary } from "./library";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listQuestions: vi.fn(),
  createQuestion: vi.fn(),
  getQuestion: vi.fn(),
  updateQuestion: vi.fn(),
  listQuestionVersions: vi.fn(),
  approveQuestion: vi.fn(),
  archiveQuestion: vi.fn(),
  restoreQuestion: vi.fn(),
  generateQuestions: vi.fn(),
}));
vi.mock("@/jobs/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/jobs/api")>()),
  listJobs: vi.fn(),
}));
vi.mock("@/candidates/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/candidates/api")>()),
  listCandidates: vi.fn(),
}));
vi.mock("@/interviews/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/interviews/api")>()),
  listTemplates: vi.fn(),
}));

function question(overrides: Partial<api.Question> = {}): api.Question {
  return {
    id: "q-1",
    category: "technical",
    status: "draft",
    source: "ai",
    version: 1,
    text: "How would you profile a slow FastAPI endpoint?",
    skill_name: "Python",
    skill_id: null,
    topic: "Performance",
    difficulty: "medium",
    type: "technical",
    expected_concepts: ["profiling"],
    rubric: [{ criterion: "Correctness", weight: 100, description: "" }],
    time_limit_seconds: 300,
    follow_up_rules: [{ when: "weak", prompt: "Which tool would you start with?" }],
    coding: null,
    generation: { model: "mock-llm" },
    approved_at: null,
    created_at: "2026-10-05T00:00:00Z",
    updated_at: "2026-10-05T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  resetNavigation("/questions");
  vi.mocked(api.listQuestions).mockResolvedValue({ items: [question()], next_cursor: null });
  vi.mocked(api.getQuestion).mockResolvedValue(question());
  vi.mocked(api.listQuestionVersions).mockResolvedValue([]);
  vi.mocked(listJobs).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(listCandidates).mockResolvedValue({ items: [], next_cursor: null });
  vi.mocked(listTemplates).mockResolvedValue({ items: [], next_cursor: null });
});

describe("QuestionLibrary", () => {
  it("marks AI drafts and approves one after review", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveQuestion).mockResolvedValue(question({ status: "approved" }));
    renderAdmin(<QuestionLibrary canManage />);

    const open = await screen.findByRole("button", { name: /Open question: How would you/ });
    const row = open.closest("tr") as HTMLElement;
    expect(within(row).getByText("Draft")).toBeInTheDocument();
    expect(within(row).getByText("AI draft")).toBeInTheDocument();

    await user.click(open);
    const sheet = await screen.findByRole("dialog", { name: "Question" });
    expect(within(sheet).getByLabelText("Question")).toHaveValue(question().text);
    await user.click(within(sheet).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.approveQuestion).toHaveBeenCalledWith("q-1"));
  });

  it("checks a new question's rubric before saving it as a draft", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createQuestion).mockResolvedValue(question({ id: "q-2", source: "manual" }));
    renderAdmin(<QuestionLibrary canManage />);

    await user.click(await screen.findByRole("button", { name: "New question" }));
    const sheet = await screen.findByRole("dialog", { name: "New question" });
    await user.type(within(sheet).getByLabelText("Question"), "Explain Python's GIL and threads.");
    await user.type(within(sheet).getByLabelText("Skill"), "Python");
    await user.click(within(sheet).getByRole("button", { name: "Add criterion" }));
    await user.type(within(sheet).getByLabelText("Criterion 1"), "Correctness");
    await user.type(within(sheet).getByLabelText("Weight of criterion 1"), "60");
    await user.click(within(sheet).getByRole("button", { name: "Save as draft" }));
    expect(within(sheet).getByRole("alert")).toHaveTextContent("add up to 100");
    expect(api.createQuestion).not.toHaveBeenCalled();

    await user.clear(within(sheet).getByLabelText("Weight of criterion 1"));
    await user.type(within(sheet).getByLabelText("Weight of criterion 1"), "100");
    await user.click(within(sheet).getByRole("button", { name: "Save as draft" }));
    await waitFor(() => expect(api.createQuestion).toHaveBeenCalled());
    const [body] = vi.mocked(api.createQuestion).mock.calls[0] ?? [];
    expect(body).toMatchObject({
      status: "draft",
      text: "Explain Python's GIL and threads.",
      skill_name: "Python",
      rubric: [{ criterion: "Correctness", weight: 100 }],
      category: null,
    });
  });

  it("generates drafts with AI and shows them for review", async () => {
    const user = userEvent.setup();
    vi.mocked(api.generateQuestions).mockResolvedValue({
      drafts: [question()],
      skipped: 1,
      model: "mock-llm",
    });
    renderAdmin(<QuestionLibrary canManage />);

    await user.click(await screen.findByRole("button", { name: "Generate with AI" }));
    const dialog = await screen.findByRole("dialog", { name: "Generate questions with AI" });
    await user.click(within(dialog).getByRole("button", { name: "Generate drafts" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Enter 1 to 10 skills.");

    await user.type(within(dialog).getByLabelText("Skills (separate with commas)"), "Python, SQL");
    await user.clear(within(dialog).getByLabelText("How many (1 to 10)"));
    await user.type(within(dialog).getByLabelText("How many (1 to 10)"), "3");
    await user.selectOptions(within(dialog).getByLabelText("Experience level"), "senior");
    await user.click(within(dialog).getByRole("button", { name: "Generate drafts" }));
    await waitFor(() =>
      expect(api.generateQuestions).toHaveBeenCalledWith({
        skills: ["Python", "SQL"],
        count: 3,
        experience_level: "senior",
        job_id: null,
        candidate_id: null,
        template_id: null,
        types: [],
      }),
    );
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith(expect.stringContaining("status=draft"), {
        scroll: false,
      }),
    );
  });

  it("is read-only without the manage permission", async () => {
    renderAdmin(<QuestionLibrary canManage={false} />);
    await screen.findByRole("button", { name: /Open question/ });
    expect(screen.queryByRole("button", { name: "New question" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate with AI" })).not.toBeInTheDocument();
  });
});
