import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DEV_SESSIONS } from "@/auth/dev-sessions";
import { resetNavigation, router } from "@/test/navigation";
import { renderWithIntl } from "@/test/render";
import { CommandMenu } from "./command-menu";

describe("CommandMenu", () => {
  it("offers only the pages the session may open", () => {
    resetNavigation();
    renderWithIntl(
      <CommandMenu open onOpenChange={() => {}} session={DEV_SESSIONS.hiring_manager} />,
    );
    const dialog = screen.getByRole("dialog", { name: "Go to" });
    expect(within(dialog).getByRole("option", { name: /Candidates/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("option", { name: /New job/ })).toBeNull();
    expect(within(dialog).queryByRole("option", { name: /Users/ })).toBeNull();
  });

  it("opens the chosen page", async () => {
    const user = userEvent.setup();
    resetNavigation();
    renderWithIntl(<CommandMenu open onOpenChange={() => {}} session={DEV_SESSIONS.org_admin} />);
    await user.type(screen.getByRole("combobox"), "audit logs");
    await user.keyboard("{Enter}");
    expect(router.push).toHaveBeenCalledWith("/admin/audit-logs");
  });
});
