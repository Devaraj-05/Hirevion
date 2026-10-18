import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import * as reports from "@/reports/api";
import { renderAdmin } from "@/test/render";
import { CandidateReportCard } from "./candidate-report-card";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("@/reports/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/reports/api")>()),
  getReportSettings: vi.fn(),
  saveReportSettings: vi.fn(),
}));

const SETTINGS = {
  completion: true,
  general_feedback: false,
  technical_feedback: false,
  coding_feedback: false,
  next_step: true,
};

describe("CandidateReportCard (admin)", () => {
  it("lets the organisation choose which of the five items recruiters may release", async () => {
    const user = userEvent.setup();
    vi.mocked(reports.getReportSettings).mockResolvedValue(SETTINGS);
    vi.mocked(reports.saveReportSettings).mockResolvedValue({
      ...SETTINGS,
      technical_feedback: true,
    });
    renderAdmin(<CandidateReportCard />);
    expect(await screen.findAllByRole("checkbox")).toHaveLength(5);
    expect(screen.getByRole("checkbox", { name: "Interview completion" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Technical feedback" })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Technical feedback" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(reports.saveReportSettings).toHaveBeenCalledWith({
        ...SETTINGS,
        technical_feedback: true,
      }),
    );
  });
});
