import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/admin/api";
import type { Permission } from "@/auth/permissions";
import { renderAdmin } from "@/test/render";
import { RolesPanel } from "./roles-panel";

// Dialogs typed into by userEvent take longer than the default 5 s when the whole suite runs.
vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/admin/api", () => ({
  listRoles: vi.fn(),
  listPermissions: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
}));

const CATALOGUE: api.CataloguePermission[] = [
  { name: "jobs.view", area: "jobs" },
  { name: "jobs.create", area: "jobs" },
  { name: "account.manage", area: "account" },
  { name: "admin.users.manage", area: "admin" },
];

const ROLES: api.Role[] = [
  {
    id: "r-recruiter",
    key: "recruiter",
    name: "Recruiter",
    description: null,
    system: true,
    permissions: ["jobs.view", "jobs.create", "account.manage"],
    member_count: 3,
  },
  {
    id: "r-sourcer",
    key: null,
    name: "Sourcer",
    description: "Finds people",
    system: false,
    permissions: ["jobs.view", "account.manage"],
    member_count: 0,
  },
];

// The signed-in user may grant jobs.* but not admin.users.manage.
const HELD: Permission[] = ["jobs.view", "jobs.create", "account.manage", "admin.roles.manage"];

beforeEach(() => {
  vi.mocked(api.listRoles).mockReset().mockResolvedValue(ROLES);
  vi.mocked(api.listPermissions).mockReset().mockResolvedValue(CATALOGUE);
  vi.mocked(api.createRole).mockReset();
  vi.mocked(api.updateRole).mockReset();
  vi.mocked(api.deleteRole).mockReset();
});

describe("RolesPanel", () => {
  it("lists built-in and custom roles, editing only custom ones", async () => {
    renderAdmin(<RolesPanel held={HELD} />);
    const list = await screen.findByRole("table", { name: "Roles" });
    const rows = within(list).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Recruiter");
    expect(rows[1]).toHaveTextContent("Built in");
    expect(rows[1]).toHaveTextContent("3 members");
    expect(within(list).queryByRole("button", { name: "Edit Recruiter" })).not.toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Edit Sourcer" })).toBeInTheDocument();
  });

  it("shows the permission matrix with headers and readable cells", async () => {
    renderAdmin(<RolesPanel held={HELD} />);
    const matrix = await screen.findByRole("table", { name: "What each role can do" });
    expect(within(matrix).getByRole("columnheader", { name: "Sourcer" })).toBeInTheDocument();
    const row = within(matrix).getByRole("row", { name: /Create jobs/ });
    const [recruiter, sourcer] = within(row).getAllByRole("cell");
    expect(recruiter).toHaveTextContent("Granted");
    expect(sourcer).toHaveTextContent("Not granted");
  });

  it("creates a role only from permissions the user holds", async () => {
    vi.mocked(api.createRole).mockResolvedValue({
      ...ROLES[1],
      id: "r-new",
      name: "Talent",
    } as api.Role);
    const user = userEvent.setup();
    renderAdmin(<RolesPanel held={HELD} />);
    await user.click(await screen.findByRole("button", { name: "New role" }));
    const dialog = await screen.findByRole("dialog", { name: "New role" });
    expect(
      within(dialog).getByRole("checkbox", { name: "Manage users and invitations" }),
    ).toBeDisabled();
    expect(
      within(dialog).queryByRole("checkbox", { name: "Manage their own account" }),
    ).not.toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Name"), "Talent");
    await user.click(within(dialog).getByRole("checkbox", { name: "Create jobs" }));
    await user.click(within(dialog).getByRole("button", { name: "Save role" }));

    await waitFor(() => expect(api.createRole).toHaveBeenCalled());
    const [body, key] = vi.mocked(api.createRole).mock.calls[0] ?? [];
    expect(body).toEqual({ name: "Talent", description: null, permissions: ["jobs.create"] });
    expect(key).toEqual(expect.any(String));
  });

  it("edits a custom role, and offers to delete it when nobody holds it", async () => {
    vi.mocked(api.updateRole).mockResolvedValue(ROLES[1] as api.Role);
    const user = userEvent.setup();
    renderAdmin(<RolesPanel held={HELD} />);
    await user.click(await screen.findByRole("button", { name: "Edit Sourcer" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Sourcer" });
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Sourcer");
    expect(within(dialog).getByRole("checkbox", { name: "View jobs" })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: "Delete role" })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("checkbox", { name: "Create jobs" }));
    await user.click(within(dialog).getByRole("button", { name: "Save role" }));
    await waitFor(() =>
      expect(api.updateRole).toHaveBeenCalledWith("r-sourcer", {
        name: "Sourcer",
        description: "Finds people",
        permissions: ["jobs.view", "jobs.create"],
      }),
    );
  });
});
