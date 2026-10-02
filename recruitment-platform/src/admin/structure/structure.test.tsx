import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/admin/api";
import { renderAdmin } from "@/test/render";
import { DepartmentsPanel } from "./departments-panel";
import { TeamsPanel } from "./teams-panel";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/admin/api", () => ({
  listDepartments: vi.fn(),
  createDepartment: vi.fn(),
  updateDepartment: vi.fn(),
  listTeams: vi.fn(),
  createTeam: vi.fn(),
  updateTeam: vi.fn(),
  listTeamMembers: vi.fn(),
  addTeamMember: vi.fn(),
  removeTeamMember: vi.fn(),
  listUsers: vi.fn(),
}));

const ENGINEERING: api.Department = {
  id: "d-eng",
  name: "Engineering",
  description: "Builders",
  archived_at: null,
  created_at: "2026-10-01T00:00:00Z",
};
const OLD: api.Department = {
  ...ENGINEERING,
  id: "d-old",
  name: "Old",
  archived_at: "2026-10-01T00:00:00Z",
};
const HIRING: api.Team = {
  id: "t-hiring",
  name: "Platform hiring",
  description: null,
  department_id: "d-eng",
  department_name: "Engineering",
  member_count: 1,
  archived_at: null,
  created_at: "2026-10-01T00:00:00Z",
};
const ASHA: api.Member = {
  id: "u-asha",
  name: "Asha Rao",
  email: "asha@acme.example.test",
  status: "active",
};
const RAVI: api.User = {
  id: "u-ravi",
  name: "Ravi Kumar",
  email: "ravi@acme.example.test",
  status: "active",
  access_scope: "organization",
  locale: "en-IN",
  roles: [],
  teams: [],
  created_at: "2026-10-01T00:00:00Z",
};

beforeEach(() => {
  vi.mocked(api.listDepartments)
    .mockReset()
    .mockImplementation(async (archived) => (archived ? [ENGINEERING, OLD] : [ENGINEERING]));
  vi.mocked(api.createDepartment).mockReset().mockResolvedValue(ENGINEERING);
  vi.mocked(api.updateDepartment).mockReset().mockResolvedValue(ENGINEERING);
  vi.mocked(api.listTeams).mockReset().mockResolvedValue([HIRING]);
  vi.mocked(api.createTeam).mockReset().mockResolvedValue(HIRING);
  vi.mocked(api.listTeamMembers).mockReset().mockResolvedValue([ASHA]);
  vi.mocked(api.addTeamMember).mockReset().mockResolvedValue();
  vi.mocked(api.removeTeamMember).mockReset().mockResolvedValue();
  vi.mocked(api.listUsers)
    .mockReset()
    .mockResolvedValue({ items: [RAVI], next_cursor: null });
});

describe("DepartmentsPanel", () => {
  it("creates a department after checking its name", async () => {
    const user = userEvent.setup();
    renderAdmin(<DepartmentsPanel />);
    await user.click(await screen.findByRole("button", { name: "New department" }));
    const dialog = await screen.findByRole("dialog", { name: "New department" });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Enter a name.")).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Name"), "Sales");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.createDepartment).toHaveBeenCalled());
    expect(vi.mocked(api.createDepartment).mock.calls[0]?.[0]).toEqual({
      name: "Sales",
      description: null,
    });
  });

  it("archives a department and shows archived ones on request", async () => {
    const user = userEvent.setup();
    renderAdmin(<DepartmentsPanel />);
    await user.click(await screen.findByRole("button", { name: "Archive Engineering" }));
    await waitFor(() =>
      expect(api.updateDepartment).toHaveBeenCalledWith("d-eng", { archived: true }),
    );

    expect(screen.queryByText("Old")).not.toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Show archived" }));
    expect(await screen.findByText("Old")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore Old" })).toBeInTheDocument();
  });
});

describe("TeamsPanel", () => {
  it("creates a team in a department", async () => {
    const user = userEvent.setup();
    renderAdmin(<TeamsPanel />);
    await user.click(await screen.findByRole("button", { name: "New team" }));
    const dialog = await screen.findByRole("dialog", { name: "New team" });
    await user.type(within(dialog).getByLabelText("Name"), "Campus");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.createTeam).toHaveBeenCalled());
    expect(vi.mocked(api.createTeam).mock.calls[0]?.[0]).toEqual({
      name: "Campus",
      description: null,
      department_id: null,
    });
  });

  it("adds and removes members", async () => {
    const user = userEvent.setup();
    renderAdmin(<TeamsPanel />);
    await user.click(await screen.findByRole("button", { name: "Members of Platform hiring" }));
    const dialog = await screen.findByRole("dialog", { name: "Members of Platform hiring" });
    expect(await within(dialog).findByText("Asha Rao")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Remove Asha Rao" }));
    await waitFor(() => expect(api.removeTeamMember).toHaveBeenCalledWith("t-hiring", "u-asha"));

    await user.type(
      within(dialog).getByRole("searchbox", { name: "Find people by name or email" }),
      "ravi{Enter}",
    );
    await user.click(await within(dialog).findByRole("button", { name: "Add Ravi Kumar" }));
    await waitFor(() => expect(api.addTeamMember).toHaveBeenCalledWith("t-hiring", "u-ravi"));
    expect(api.listUsers).toHaveBeenCalledWith({ q: "ravi", limit: 10 });
  });
});
