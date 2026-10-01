import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DEV_SESSIONS } from "@/auth/dev-sessions";
import { resetNavigation } from "@/test/navigation";
import { renderWithIntl } from "@/test/render";
import { Sidebar } from "./sidebar";

function linkNames(): string[] {
  const nav = screen.getByRole("navigation", { name: "Main" });
  return within(nav)
    .getAllByRole("link")
    .map((link) => link.textContent ?? "");
}

describe("Sidebar", () => {
  it("lists only the sections the session may open, in manifest order", () => {
    resetNavigation();
    renderWithIntl(<Sidebar session={DEV_SESSIONS.recruiter} collapsed={false} />);
    expect(linkNames()).toEqual([
      "Dashboard",
      "Jobs",
      "Candidates",
      "Interviews",
      "Question library",
      "Reports",
    ]);
  });

  it("shows the super admin every section, the platform included", () => {
    resetNavigation();
    renderWithIntl(<Sidebar session={DEV_SESSIONS.super_admin} collapsed={false} />);
    expect(linkNames()).toContain("Administration");
    expect(linkNames().at(-1)).toBe("Platform");
  });

  it("marks the current section, on its sub-pages too", () => {
    resetNavigation("/jobs/new");
    renderWithIntl(<Sidebar session={DEV_SESSIONS.recruiter} collapsed={false} />);
    expect(screen.getByRole("link", { name: "Jobs" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("keeps every link's name when collapsed to icons", () => {
    resetNavigation();
    renderWithIntl(<Sidebar session={DEV_SESSIONS.recruiter} collapsed />);
    expect(screen.getByRole("link", { name: "Candidates" })).toBeInTheDocument();
  });
});
