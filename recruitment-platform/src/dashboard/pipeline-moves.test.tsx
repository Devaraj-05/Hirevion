import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as review from "@/review/api";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin, renderWithIntl } from "@/test/render";
import { LivePipeline } from "./live-pipeline";
import type { PipelineCard } from "./model";
import { PipelineBoard } from "./pipeline-board";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("@/review/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/review/api")>()),
  getPipeline: vi.fn(),
  changeHiringStatus: vi.fn(),
}));

const CARD: PipelineCard = {
  id: "app-1",
  name: "Asha Rao",
  job: "Backend Engineer",
  href: "/candidates/c-1",
  moves: ["shortlisted", "on_hold"],
};

describe("PipelineBoard moves", () => {
  it("moves a card from its menu, the way to do it by keyboard or touch", async () => {
    const user = userEvent.setup();
    const onMove = vi.fn();
    renderWithIntl(<PipelineBoard columns={{ under_review: [CARD] }} onMove={onMove} />);
    const menu = screen.getByRole("combobox", { name: "Move Asha Rao" });
    expect(
      within(menu)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Move to…", "Shortlisted", "On hold"]);
    await user.selectOptions(menu, "on_hold");
    expect(onMove).toHaveBeenCalledWith(CARD, "on_hold");
    expect(screen.getByRole("link", { name: "Asha Rao" })).toHaveAttribute(
      "href",
      "/candidates/c-1",
    );
  });

  it("also moves by dragging, only to a column the card allows", () => {
    const onMove = vi.fn();
    renderWithIntl(<PipelineBoard columns={{ under_review: [CARD] }} onMove={onMove} />);
    const card = screen.getByText("Asha Rao").closest("li") as HTMLElement;
    expect(card).toHaveAttribute("draggable", "true");
    fireEvent.dragStart(card);
    fireEvent.drop(screen.getByRole("region", { name: "Rejected" }));
    expect(onMove).not.toHaveBeenCalled(); // rejected isn't among its moves
    fireEvent.dragStart(card);
    fireEvent.drop(screen.getByRole("region", { name: "Shortlisted" }));
    expect(onMove).toHaveBeenCalledWith(CARD, "shortlisted");
  });

  it("is a plain view without onMove, or for a card that can't move", () => {
    const view = renderWithIntl(<PipelineBoard columns={{ under_review: [CARD] }} />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    view.unmount();
    renderWithIntl(
      <PipelineBoard columns={{ under_review: [{ ...CARD, moves: [] }] }} onMove={vi.fn()} />,
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText("Asha Rao").closest("li")).toHaveAttribute("draggable", "false");
  });

  it("shows a column's whole count when it holds more than its cards", () => {
    renderWithIntl(
      <PipelineBoard columns={{ shortlisted: [CARD] }} counts={{ shortlisted: 120 }} />,
    );
    expect(
      within(screen.getByRole("region", { name: "Shortlisted" })).getByText("120"),
    ).toBeInTheDocument();
  });
});

const BOARD = (): review.Pipeline => ({
  columns: [
    {
      status: "under_review",
      count: 1,
      cards: [
        {
          application_id: "app-1",
          candidate_id: "c-1",
          candidate_name: "Asha Rao",
          job_id: "j-1",
          job_title: "Backend Engineer",
          interview_id: null,
          moves: ["shortlisted", "on_hold", "rejected"],
        },
      ],
    },
    { status: "shortlisted", count: 0, cards: [] },
  ],
});

describe("LivePipeline", () => {
  beforeEach(() => {
    resetNavigation("/dashboard");
    vi.mocked(review.getPipeline).mockResolvedValue(BOARD());
  });

  it("changes the status at once when no reason is needed", async () => {
    const user = userEvent.setup();
    vi.mocked(review.changeHiringStatus).mockResolvedValue({
      status: "shortlisted",
    } as review.HiringState);
    renderAdmin(<LivePipeline />);
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Move Asha Rao" }),
      "shortlisted",
    );
    await waitFor(() =>
      expect(review.changeHiringStatus).toHaveBeenCalledWith("app-1", {
        status: "shortlisted",
        reason: null,
      }),
    );
  });

  it("asks why before a move that needs a reason", async () => {
    const user = userEvent.setup();
    vi.mocked(review.changeHiringStatus).mockResolvedValue({
      status: "on_hold",
    } as review.HiringState);
    renderAdmin(<LivePipeline />);
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Move Asha Rao" }),
      "on_hold",
    );
    expect(review.changeHiringStatus).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog", { name: "Change the hiring status" });
    expect(within(dialog).getByLabelText("Move to")).toHaveValue("on_hold");
    await user.type(within(dialog).getByLabelText("Why?"), "Waiting on budget");
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() =>
      expect(review.changeHiringStatus).toHaveBeenCalledWith("app-1", {
        status: "on_hold",
        reason: "Waiting on budget",
      }),
    );
  });
});
