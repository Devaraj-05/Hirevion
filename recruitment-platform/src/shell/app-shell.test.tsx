import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEV_SESSIONS } from "@/auth/dev-sessions";
import type { Session } from "@/auth/permissions";
import { resetNavigation } from "@/test/navigation";
import { renderWithIntl } from "@/test/render";
import { AppShell } from "./app-shell";

vi.mock("@/auth/dev-actions", () => ({ signInAsDevRole: vi.fn(), signOut: vi.fn() }));

function renderShell(session: Session = DEV_SESSIONS.recruiter, path = "/dashboard") {
  resetNavigation(path);
  renderWithIntl(
    <AppShell session={session} devTools={false} initialCollapsed={false}>
      <p>Page content</p>
    </AppShell>,
  );
  return userEvent.setup();
}

describe("AppShell", () => {
  it("puts the skip link first, pointing at the main content", async () => {
    const user = renderShell();
    await user.tab();
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveFocus();
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(within(screen.getByRole("main")).getByText("Page content")).toBeInTheDocument();
  });

  it("remembers a collapsed sidebar", async () => {
    const user = renderShell();
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(document.cookie).toContain("hv_sidebar=collapsed");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("shows where the page sits", () => {
    renderShell(DEV_SESSIONS.org_admin, "/admin/users");
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByRole("link", { name: "Administration" })).toHaveAttribute(
      "href",
      "/admin",
    );
    expect(within(trail).getByText("Users")).toHaveAttribute("aria-current", "page");
  });

  it("opens the command palette with Ctrl+K and from the search button", async () => {
    const user = renderShell();
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog", { name: "Go to" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Go to" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /Search pages/ }));
    expect(screen.getByRole("dialog", { name: "Go to" })).toBeInTheDocument();
  });

  it("opens the notification panel", async () => {
    const user = renderShell();
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    const panel = screen.getByRole("dialog", { name: "Notifications" });
    expect(within(panel).getByText("You're all caught up")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "See all notifications" })).toHaveAttribute(
      "href",
      "/notifications",
    );
  });
});
