import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RoutePath } from "@/auth/manifest";
import { useShortcuts } from "./use-shortcuts";

interface HarnessProps {
  navigate: (path: RoutePath) => void;
  onPalette?: () => void;
  allowed?: (path: RoutePath) => boolean;
}

function Harness({ navigate, onPalette = () => {}, allowed = () => true }: HarnessProps) {
  useShortcuts({ navigate, onPalette, allowed });
  return <input aria-label="Notes" />;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useShortcuts", () => {
  it("goes to a section with g and its letter", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    render(<Harness navigate={navigate} />);
    await user.keyboard("gj");
    expect(navigate).toHaveBeenLastCalledWith("/jobs");
    await user.keyboard("gr");
    expect(navigate).toHaveBeenLastCalledWith("/reports");
  });

  it("leaves typing alone", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    render(<Harness navigate={navigate} />);
    await user.click(screen.getByRole("textbox", { name: "Notes" }));
    await user.keyboard("gj");
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveValue("gj");
  });

  it("skips sections the session can't open", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    render(<Harness navigate={navigate} allowed={(path) => path !== "/jobs"} />);
    await user.keyboard("gj");
    expect(navigate).not.toHaveBeenCalled();
  });

  // The clock is moved by hand: fake timers would also freeze Testing Library's own waits.
  it("forgets a lone g after a pause", async () => {
    const clock = vi.spyOn(Date, "now").mockReturnValue(10_000);
    const user = userEvent.setup();
    const navigate = vi.fn();
    render(<Harness navigate={navigate} />);
    await user.keyboard("g");
    clock.mockReturnValue(11_500);
    await user.keyboard("j");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("opens the palette with Ctrl+K, even from a field", async () => {
    const user = userEvent.setup();
    const onPalette = vi.fn();
    render(<Harness navigate={vi.fn()} onPalette={onPalette} />);
    await user.click(screen.getByRole("textbox", { name: "Notes" }));
    await user.keyboard("{Control>}k{/Control}");
    expect(onPalette).toHaveBeenCalledTimes(1);
  });
});
