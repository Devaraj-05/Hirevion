import { ApiProblem } from "@hirevion/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/admin/api";
import { resetNavigation, router } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import { UsersTable } from "./users-table";

// Dialogs typed into by userEvent take longer than the default 5 s when the whole suite runs.
vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/admin/api", () => ({
  listUsers: vi.fn(),
  listRoles: vi.fn(),
  listTeams: vi.fn(),
  inviteUser: vi.fn(),
  getUser: vi.fn(),
  updateUser: vi.fn(),
  setUserRoles: vi.fn(),
  disableUser: vi.fn(),
  enableUser: vi.fn(),
  resendInvitation: vi.fn(),
  cancelInvitation: vi.fn(),
}));

const ROLES: api.Role[] = [
  {
    id: "r-admin",
    key: "org_admin",
    name: "Organisation admin",
    description: null,
    system: true,
    permissions: [],
    member_count: 1,
  },
  {
    id: "r-recruiter",
    key: "recruiter",
    name: "Recruiter",
    description: null,
    system: true,
    permissions: [],
    member_count: 1,
  },
  {
    id: "r-sourcer",
    key: null,
    name: "Sourcer",
    description: null,
    system: false,
    permissions: [],
    member_count: 0,
  },
];

const TEAMS: api.Team[] = [
  {
    id: "t-campus",
    name: "Campus",
    description: null,
    department_id: null,
    department_name: null,
    member_count: 0,
    archived_at: null,
    created_at: "2026-10-01T00:00:00Z",
  },
];

function user(overrides: Partial<api.User>): api.User {
  return {
    id: "u-1",
    name: "Asha Rao",
    email: "asha@acme.example.test",
    status: "active",
    access_scope: "organization",
    locale: "en-IN",
    roles: [{ id: "r-recruiter", key: "recruiter", name: "Recruiter" }],
    teams: [],
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

const ASHA = user({});
const RAVI = user({
  id: "u-2",
  name: "Ravi Kumar",
  email: "ravi@acme.example.test",
  status: "invited",
  roles: [{ id: "r-sourcer", key: null, name: "Sourcer" }],
  teams: [{ id: "t-campus", name: "Campus" }],
});

beforeEach(() => {
  resetNavigation("/admin/users");
  vi.mocked(api.listUsers)
    .mockReset()
    .mockResolvedValue({ items: [ASHA, RAVI], next_cursor: null });
  vi.mocked(api.listRoles).mockReset().mockResolvedValue(ROLES);
  vi.mocked(api.listTeams).mockReset().mockResolvedValue(TEAMS);
  vi.mocked(api.inviteUser).mockReset();
  vi.mocked(api.getUser).mockReset();
});

describe("UsersTable", () => {
  it("lists users with their translated roles, teams and status", async () => {
    renderAdmin(<UsersTable />);
    await screen.findByRole("button", { name: "Open Asha Rao" });
    const rows = within(screen.getByRole("table", { name: "Users" })).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Asha Rao");
    expect(rows[1]).toHaveTextContent("Recruiter");
    expect(rows[1]).toHaveTextContent("Active");
    expect(rows[2]).toHaveTextContent("Sourcer");
    expect(rows[2]).toHaveTextContent("Campus");
    expect(rows[2]).toHaveTextContent("Invited");
  });

  it("puts the search in the URL", async () => {
    const user = userEvent.setup();
    renderAdmin(<UsersTable />);
    await user.type(
      await screen.findByRole("searchbox", { name: "Search by name or email" }),
      "ravi{Enter}",
    );
    expect(router.replace).toHaveBeenCalledWith("/admin/users?q=ravi", { scroll: false });
  });

  it("checks an invitation before sending it", async () => {
    const user = userEvent.setup();
    renderAdmin(<UsersTable />);
    await user.click(await screen.findByRole("button", { name: "Invite user" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite a user" });
    await user.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    expect(await within(dialog).findByText("Enter an email address.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter their name.")).toBeInTheDocument();
    expect(within(dialog).getByText("Choose at least one role.")).toBeInTheDocument();
    expect(api.inviteUser).not.toHaveBeenCalled();
  });

  it("sends an invitation and closes", async () => {
    vi.mocked(api.inviteUser).mockResolvedValue(user({ id: "u-3", status: "invited" }));
    const user_ = userEvent.setup();
    renderAdmin(<UsersTable />);
    await user_.click(await screen.findByRole("button", { name: "Invite user" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite a user" });
    await user_.type(within(dialog).getByLabelText("Email"), "hema@acme.example.test");
    await user_.type(within(dialog).getByLabelText("Name"), "Hema Iyer");
    await user_.click(within(dialog).getByRole("checkbox", { name: "Recruiter" }));
    await user_.click(within(dialog).getByRole("checkbox", { name: "Campus" }));
    await user_.click(within(dialog).getByRole("radio", { name: "Their teams' work" }));
    await user_.click(within(dialog).getByRole("button", { name: "Send invitation" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [body, key] = vi.mocked(api.inviteUser).mock.calls[0] ?? [];
    expect(body).toEqual({
      email: "hema@acme.example.test",
      name: "Hema Iyer",
      role_ids: ["r-recruiter"],
      team_ids: ["t-campus"],
      access_scope: "teams",
      locale: "en-IN",
    });
    expect(key).toEqual(expect.any(String));
  });

  it("marks an address that's already in use", async () => {
    vi.mocked(api.inviteUser).mockRejectedValue(
      new ApiProblem({
        type: "urn:hirevion:problem:email-taken",
        title: "This email address already has an account",
        status: 409,
        code: "email-taken",
        errors: [{ detail: "This email address already has an account", pointer: "#/email" }],
      }),
    );
    const user_ = userEvent.setup();
    renderAdmin(<UsersTable />);
    await user_.click(await screen.findByRole("button", { name: "Invite user" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite a user" });
    await user_.type(within(dialog).getByLabelText("Email"), "asha@acme.example.test");
    await user_.type(within(dialog).getByLabelText("Name"), "Asha");
    await user_.click(within(dialog).getByRole("checkbox", { name: "Recruiter" }));
    await user_.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    expect(
      await within(dialog).findByText("This email address already has an account."),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("offers to resend or cancel only an invitation", async () => {
    vi.mocked(api.getUser).mockImplementation(async (id) => (id === RAVI.id ? RAVI : ASHA));
    const user_ = userEvent.setup();
    renderAdmin(<UsersTable />);

    await user_.click(await screen.findByRole("button", { name: "Open Ravi Kumar" }));
    let sheet = await screen.findByRole("dialog", { name: "Ravi Kumar" });
    expect(within(sheet).getByRole("button", { name: "Resend invitation" })).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Cancel invitation" })).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: "Disable user" })).not.toBeInTheDocument();
    await user_.keyboard("{Escape}");

    await user_.click(await screen.findByRole("button", { name: "Open Asha Rao" }));
    sheet = await screen.findByRole("dialog", { name: "Asha Rao" });
    expect(within(sheet).getByRole("button", { name: "Disable user" })).toBeInTheDocument();
    expect(
      within(sheet).queryByRole("button", { name: "Resend invitation" }),
    ).not.toBeInTheDocument();
  });
});
