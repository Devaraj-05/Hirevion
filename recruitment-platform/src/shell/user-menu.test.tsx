import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { signInAsDevRole, signOut } from "@/auth/dev-actions";
import { DEV_SESSIONS } from "@/auth/dev-sessions";
import { resetNavigation, router } from "@/test/navigation";
import { renderWithIntl } from "@/test/render";
import { UserMenu } from "./user-menu";

vi.mock("@/auth/dev-actions", () => ({ signInAsDevRole: vi.fn(), signOut: vi.fn() }));

beforeEach(() => {
  resetNavigation("/jobs");
  vi.mocked(signInAsDevRole).mockReset();
  vi.mocked(signOut).mockReset();
});

async function openMenu(devTools = false) {
  const user = userEvent.setup();
  renderWithIntl(<UserMenu session={DEV_SESSIONS.recruiter} devTools={devTools} />);
  await user.click(screen.getByRole("button", { name: "Your account" }));
  return user;
}

describe("UserMenu", () => {
  it("shows who is signed in, and where", async () => {
    await openMenu();
    expect(screen.getByText("Ravi Recruiter")).toBeInTheDocument();
    expect(screen.getByText("ravi@example.test")).toBeInTheDocument();
    expect(screen.getByText("Acme Talent (dev)")).toBeInTheDocument();
  });

  it("switches the language for the next render", async () => {
    const user = await openMenu();
    await user.click(screen.getByRole("menuitemradio", { name: "English (United States)" }));
    expect(document.cookie).toContain("hv_locale=en-US");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("offers the role switcher only with the development tools", async () => {
    await openMenu(false);
    expect(screen.queryByRole("menuitemradio", { name: "Hiring manager" })).toBeNull();
  });

  it("switches role through the development sign-in, staying on the page", async () => {
    const user = await openMenu(true);
    await user.click(screen.getByRole("menuitemradio", { name: "Hiring manager" }));
    const form = vi.mocked(signInAsDevRole).mock.calls[0]?.[0];
    expect(form?.get("role")).toBe("hiring_manager");
    expect(form?.get("next")).toBe("/jobs");
  });

  it("signs out", async () => {
    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalled();
  });
});
