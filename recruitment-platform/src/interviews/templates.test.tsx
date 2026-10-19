import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listQuestions } from "@/questions/api";
import { resetNavigation, router } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { InterviewDefaultsCard } from "./defaults-card";
import { TemplateForm } from "./template-form";
import { TemplatePage } from "./template-page";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  createTemplate: vi.fn(),
  getTemplate: vi.fn(),
  updateTemplate: vi.fn(),
  listTemplateVersions: vi.fn(),
  getSkillMatrix: vi.fn(),
  previewSkillMatrix: vi.fn(),
  setTemplateArchived: vi.fn(),
  getInterviewDefaults: vi.fn(),
  saveInterviewDefaults: vi.fn(),
}));
vi.mock("@/questions/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/questions/api")>()),
  listQuestions: vi.fn(),
  getQuestion: vi.fn(),
}));

const DEFAULTS: api.InterviewDefaults = {
  duration_minutes: 45,
  question_count: 10,
  difficulty: { easy: 20, medium: 50, hard: 30 },
  question_types: ["technical", "conceptual"],
  use_resume: true,
  use_jd: true,
  adaptive_follow_ups: true,
  coding: { enabled: false, languages: ["python"], minutes: 20 },
  proctoring_level: "standard",
  third_eye: "optional",
  recording: { screen: true, camera: true, audio: true },
  rubric: [
    { dimension: "relevance", weight: 13 },
    { dimension: "correctness", weight: 13 },
    { dimension: "completeness", weight: 13 },
    { dimension: "technical_depth", weight: 13 },
    { dimension: "reasoning", weight: 12 },
    { dimension: "clarity", weight: 12 },
    { dimension: "communication", weight: 12 },
    { dimension: "evidence", weight: 12 },
  ],
  proctoring_presets: { off: [], basic: ["face", "focus"], standard: ["face"], strict: ["face"] },
};

function template(overrides: Partial<api.Template> = {}): api.Template {
  const { proctoring_presets: _, ...settings } = DEFAULTS;
  return {
    id: "t-1",
    name: "Backend screen",
    description: "",
    status: "active",
    version: 2,
    duration_minutes: 60,
    question_count: 10,
    proctoring_level: "standard",
    third_eye: "optional",
    coding: false,
    updated_at: "2026-10-05T00:00:00Z",
    current: {
      ...settings,
      duration_minutes: 60,
      version: 2,
      name: "Backend screen",
      skills: [{ name: "Python", weight: 100, skill_id: null }],
      questions: [],
      created_by: null,
      created_at: "2026-10-05T00:00:00Z",
    },
    ...overrides,
  };
}

const MATRIX: api.MatrixRow[] = [
  {
    skill: "Python",
    weight: 100,
    questions: 10,
    by_difficulty: { easy: 2, medium: 5, hard: 3 },
    available: { easy: 2, medium: 1, hard: 0 },
    gaps: { medium: 4, hard: 3 },
  },
];

beforeEach(() => {
  resetNavigation("/interviews/templates/new");
  vi.mocked(api.getInterviewDefaults).mockResolvedValue(DEFAULTS);
  vi.mocked(api.previewSkillMatrix).mockResolvedValue(MATRIX);
  vi.mocked(api.getSkillMatrix).mockResolvedValue(MATRIX);
  vi.mocked(listQuestions).mockResolvedValue({ items: [], next_cursor: null });
});

describe("TemplateForm", () => {
  it("starts from the defaults and creates the template", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createTemplate).mockResolvedValue(template({ version: 1 }));
    renderAdmin(<TemplateForm canManage />);

    expect(await screen.findByLabelText("Duration in minutes")).toHaveValue(45);
    await user.type(screen.getByLabelText("Name"), "Backend screen");
    await user.type(screen.getByLabelText("Skill 1"), "Python");
    expect(await screen.findByText("7 short")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create template" }));

    await waitFor(() => expect(api.createTemplate).toHaveBeenCalled());
    const [body] = vi.mocked(api.createTemplate).mock.calls[0] ?? [];
    expect(body).toMatchObject({
      name: "Backend screen",
      skills: [{ name: "Python", weight: 100 }],
      duration_minutes: 45,
      difficulty: { easy: 20, medium: 50, hard: 30 },
      proctoring_level: "standard",
      questions: [],
    });
    expect(body?.rubric).toHaveLength(8);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/interviews/templates/t-1"));
  });

  it("won't save a difficulty mix or skill weights that don't add up", async () => {
    const user = userEvent.setup();
    renderAdmin(<TemplateForm canManage />);

    await user.type(await screen.findByLabelText("Name"), "Mixed up");
    await user.type(screen.getByLabelText("Skill 1"), "Python");
    await user.click(screen.getByRole("button", { name: "Add skill" }));
    await user.type(screen.getByLabelText("Skill 2"), "SQL");
    await user.type(screen.getByLabelText("Weight of skill 2"), "20");
    const hard = screen.getByLabelText("Hard");
    await user.clear(hard);
    await user.type(hard, "40");
    await user.click(screen.getByRole("button", { name: "Create template" }));

    const alerts = screen.getAllByRole("alert").map((alert) => alert.textContent);
    expect(alerts).toContain("Name every skill and make the weights add up to 100 (now 120).");
    expect(alerts).toContain("The difficulty mix must add up to 100 (now 110).");
    expect(api.createTemplate).not.toHaveBeenCalled();
  });
});

describe("settings checks", () => {
  it("sends a valid coding time even when coding is switched off over a typo", async () => {
    const user = userEvent.setup();
    vi.mocked(api.saveInterviewDefaults).mockResolvedValue(DEFAULTS);
    renderAdmin(<InterviewDefaultsCard />);
    await user.click(await screen.findByLabelText("Include a coding exercise"));
    const minutes = await screen.findByLabelText("Minutes for coding");
    await user.clear(minutes);
    await user.type(minutes, "200");
    await user.click(screen.getByLabelText("Include a coding exercise"));
    await user.click(screen.getByRole("button", { name: "Save defaults" }));
    await waitFor(() => expect(api.saveInterviewDefaults).toHaveBeenCalled());
    const [body] = vi.mocked(api.saveInterviewDefaults).mock.calls[0] ?? [];
    expect(body?.coding).toMatchObject({ enabled: false, minutes: 20 });
  });

  it("explains a share outside 0 to 100 even when the total is 100, and coding longer than the interview", async () => {
    const user = userEvent.setup();
    renderAdmin(<InterviewDefaultsCard />);
    const easy = await screen.findByLabelText("Easy");
    await user.clear(easy);
    await user.type(easy, "-20");
    await user.clear(screen.getByLabelText("Medium"));
    await user.type(screen.getByLabelText("Medium"), "90");
    await user.clear(screen.getByLabelText("Hard"));
    await user.type(screen.getByLabelText("Hard"), "30");
    const duration = screen.getByLabelText("Duration in minutes");
    await user.clear(duration);
    await user.type(duration, "15");
    await user.click(screen.getByLabelText("Include a coding exercise"));
    const minutes = await screen.findByLabelText("Minutes for coding");
    await user.clear(minutes);
    await user.type(minutes, "60");
    await user.click(screen.getByRole("button", { name: "Save defaults" }));
    const alerts = screen.getAllByRole("alert").map((alert) => alert.textContent);
    expect(alerts).toContain("Each share is a whole number from 0 to 100.");
    expect(alerts).toContain("The coding time can't be longer than the interview.");
    expect(api.saveInterviewDefaults).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Minutes for coding")).toHaveAccessibleDescription(
      "The coding time can't be longer than the interview.",
    );
  });

  it("says when the defaults could not be loaded", async () => {
    vi.mocked(api.getInterviewDefaults).mockRejectedValue(new Error("offline"));
    renderAdmin(<InterviewDefaultsCard />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't be loaded/);
  });
});

describe("TemplatePage", () => {
  it("keeps half-edited settings when you look at the versions", async () => {
    const user = userEvent.setup();
    resetNavigation("/interviews/templates/t-1");
    vi.mocked(api.getTemplate).mockResolvedValue(template());
    vi.mocked(api.listTemplateVersions).mockResolvedValue([template().current]);
    renderAdmin(<TemplatePage id="t-1" canManage />);
    const duration = await screen.findByLabelText("Duration in minutes");
    await user.clear(duration);
    await user.type(duration, "75");
    await user.click(screen.getByRole("tab", { name: "Versions" }));
    await screen.findByRole("list", { name: "Versions" });
    await user.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByLabelText("Duration in minutes")).toHaveValue(75);
  });

  it("says when the skill matrix could not be loaded, not that it is empty", async () => {
    const user = userEvent.setup();
    resetNavigation("/interviews/templates/t-1");
    vi.mocked(api.getTemplate).mockResolvedValue(template());
    vi.mocked(api.getSkillMatrix).mockRejectedValue(new Error("offline"));
    renderAdmin(<TemplatePage id="t-1" canManage />);
    await user.click(await screen.findByRole("tab", { name: "Skill matrix" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't be loaded/);
  });

  it("saves an edit as the next version and keeps the old ones listed", async () => {
    const user = userEvent.setup();
    resetNavigation("/interviews/templates/t-1");
    vi.mocked(api.getTemplate).mockResolvedValue(template());
    vi.mocked(api.updateTemplate).mockResolvedValue(template({ version: 3 }));
    vi.mocked(api.listTemplateVersions).mockResolvedValue([
      { ...template().current, version: 1, duration_minutes: 45 },
      template().current,
    ]);
    renderAdmin(<TemplatePage id="t-1" canManage />);

    expect(await screen.findByRole("heading", { name: "Backend screen" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Proctoring"), "strict");
    await user.click(screen.getByRole("button", { name: "Save as version 3" }));
    await waitFor(() => expect(api.updateTemplate).toHaveBeenCalled());
    const [id, body] = vi.mocked(api.updateTemplate).mock.calls[0] ?? [];
    expect(id).toBe("t-1");
    expect(body).toMatchObject({ proctoring_level: "strict", duration_minutes: 60 });

    await user.click(screen.getByRole("tab", { name: "Versions" }));
    const versions = await screen.findByRole("list", { name: "Versions" });
    expect(within(versions).getAllByRole("listitem")).toHaveLength(2);
    expect(within(versions).getByText(/45 minutes/)).toBeInTheDocument();
  });

  it("archives the template", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getTemplate).mockResolvedValue(template());
    vi.mocked(api.setTemplateArchived).mockResolvedValue(template({ status: "archived" }));
    renderAdmin(<TemplatePage id="t-1" canManage />);

    await user.click(await screen.findByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.setTemplateArchived).toHaveBeenCalledWith("t-1", true));
  });
});

describe("InterviewDefaultsCard", () => {
  it("saves the organisation's defaults", async () => {
    const user = userEvent.setup();
    vi.mocked(api.saveInterviewDefaults).mockResolvedValue({ ...DEFAULTS, duration_minutes: 30 });
    renderAdmin(<InterviewDefaultsCard />);

    const duration = await screen.findByLabelText("Duration in minutes");
    await user.clear(duration);
    await user.type(duration, "30");
    await user.selectOptions(screen.getByLabelText("Third eye (phone camera)"), "required");
    await user.click(screen.getByRole("button", { name: "Save defaults" }));
    await waitFor(() => expect(api.saveInterviewDefaults).toHaveBeenCalled());
    const [body] = vi.mocked(api.saveInterviewDefaults).mock.calls[0] ?? [];
    expect(body).toMatchObject({ duration_minutes: 30, third_eye: "required" });
  });
});
