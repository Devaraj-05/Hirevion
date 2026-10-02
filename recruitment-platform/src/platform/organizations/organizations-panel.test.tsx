import { ApiProblem } from "@hirevion/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/admin/api";
import { resetNavigation } from "@/test/navigation";
import { renderAdmin } from "@/test/render";
import { OrganizationsPanel } from "./organizations-panel";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/admin/api", () => ({
  listOrganizations: vi.fn(),
  createOrganization: vi.fn(),
  suspendOrganization: vi.fn(),
  reactivateOrganization: vi.fn(),
  inviteOrganizationAdmin: vi.fn(),
}));

const PLATFORM_ID = "00000000-0000-7000-8000-000000000001";
const ACME: api.OrganizationListing = {
  id: "o-acme",
  name: "Acme Talent",
  slug: "acme",
  status: "active",
  created_at: "2026-10-01T00:00:00Z",
  user_count: 4,
};
const PLATFORM: api.OrganizationListing = {
  ...ACME,
  id: PLATFORM_ID,
  name: "Platform",
  slug: "platform",
};

beforeEach(() => {
  resetNavigation("/platform/organizations");
  vi.mocked(api.listOrganizations)
    .mockReset()
    .mockResolvedValue({ items: [ACME, PLATFORM], next_cursor: null });
  vi.mocked(api.createOrganization).mockReset();
  vi.mocked(api.suspendOrganization)
    .mockReset()
    .mockResolvedValue({ ...ACME, status: "suspended" });
});

describe("OrganizationsPanel", () => {
  it("suggests a short name and points a clash at it", async () => {
    vi.mocked(api.createOrganization).mockRejectedValue(
      new ApiProblem({
        type: "urn:hirevion:problem:slug-taken",
        title: "Another organisation uses this slug",
        status: 409,
        code: "slug-taken",
        errors: [{ detail: "Another organisation uses this slug", pointer: "#/slug" }],
      }),
    );
    const user = userEvent.setup();
    renderAdmin(<OrganizationsPanel />);
    await user.click(await screen.findByRole("button", { name: "New organisation" }));
    const dialog = await screen.findByRole("dialog", { name: "New organisation" });
    await user.type(within(dialog).getByLabelText("Name"), "Initech Systems");
    expect(within(dialog).getByLabelText("Short name")).toHaveValue("initech-systems");

    await user.type(within(dialog).getByLabelText("First admin's name"), "Ian Admin");
    await user.type(
      within(dialog).getByLabelText("First admin's email"),
      "ian@initech.example.test",
    );
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(
      await within(dialog).findByText("Another organisation uses this slug."),
    ).toBeInTheDocument();
    expect(vi.mocked(api.createOrganization).mock.calls[0]?.[0]).toEqual({
      name: "Initech Systems",
      slug: "initech-systems",
      admin_name: "Ian Admin",
      admin_email: "ian@initech.example.test",
    });
  });

  it("suspends with a reason", async () => {
    const user = userEvent.setup();
    renderAdmin(<OrganizationsPanel />);
    await user.click(await screen.findByRole("button", { name: "Actions for Acme Talent" }));
    await user.click(await screen.findByRole("menuitem", { name: "Suspend" }));
    const dialog = await screen.findByRole("dialog", { name: "Suspend Acme Talent" });
    await user.type(within(dialog).getByLabelText("Reason"), "Trial ended");
    await user.click(within(dialog).getByRole("button", { name: "Suspend" }));
    await waitFor(() =>
      expect(api.suspendOrganization).toHaveBeenCalledWith("o-acme", "Trial ended"),
    );
  });

  it("offers no actions on the platform itself", async () => {
    renderAdmin(<OrganizationsPanel />);
    await screen.findByRole("button", { name: "Actions for Acme Talent" });
    expect(screen.queryByRole("button", { name: "Actions for Platform" })).not.toBeInTheDocument();
    expect(screen.getByText("The platform itself")).toBeInTheDocument();
  });
});
