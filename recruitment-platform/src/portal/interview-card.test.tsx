import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/render";
import { InterviewCard, type PortalInterview } from "./interview-card";

const NOW = "2026-10-12T04:30:00Z";

function interview(overrides: Partial<PortalInterview> = {}): PortalInterview {
  return {
    id: "0199-iv",
    reference: "IV-0042",
    job_title: "Backend Engineer",
    status: "invited",
    starts_at: "2026-10-13T06:30:00Z",
    expires_at: "2026-10-14T18:29:00Z",
    timezone: "Asia/Kolkata",
    duration_minutes: 45,
    can_take: false,
    third_eye: "optional",
    recorded: "your screen, camera and microphone, and the conversation's transcript",
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
  vi.setSystemTime(new Date(NOW));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("InterviewCard", () => {
  it("shows the job, the window in the interview's time zone and when it opens", () => {
    renderWithIntl(<InterviewCard interview={interview()} serverNow={NOW} />);
    expect(screen.getByRole("heading", { name: "Backend Engineer" })).toBeVisible();
    expect(screen.getByText("Invited")).toBeVisible();
    expect(screen.getByText(/13 Oct 2026/)).toBeVisible();
    expect(screen.getByText("45 minutes")).toBeVisible();
    expect(screen.getByText("Opens in 1 day 2 hours")).toBeVisible();
    expect(screen.getByRole("link", { name: "Ask to reschedule" })).toHaveAttribute(
      "href",
      "/requests?kind=reschedule&interview=0199-iv",
    );
  });

  it("counts down to the window's end once it opens, then says it has closed", () => {
    const open = interview({ starts_at: "2026-10-12T04:00:00Z", can_take: true });
    renderWithIntl(<InterviewCard interview={open} serverNow={NOW} />);
    expect(screen.getByText("Open now: start it in the Hirevion interview app.")).toBeVisible();
    expect(screen.getByText("Closes in 2 days 13 hours")).toBeVisible();
    act(() => {
      vi.advanceTimersByTime(3 * 86_400_000);
    });
    expect(screen.getByText("The window has closed.")).toBeVisible();
  });

  it("offers no reschedule for an interview that has run", () => {
    renderWithIntl(
      <InterviewCard interview={interview({ status: "completed" })} serverNow={NOW} />,
    );
    expect(screen.getByText("Completed")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Ask to reschedule" })).toBeNull();
    expect(screen.queryByText(/Opens in/)).toBeNull();
  });
});
