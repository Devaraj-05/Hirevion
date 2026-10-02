import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/admin/api";
import { renderAdmin } from "@/test/render";
import { OrganizationForm } from "./organization-form";

vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/admin/api", () => ({ getOrganization: vi.fn(), updateOrganization: vi.fn() }));

const PROFILE: api.OrganizationProfile = {
  id: "o-1",
  name: "Acme Talent",
  slug: "acme",
  status: "active",
  website: null,
  country: "IN",
  timezone: "Asia/Kolkata",
  default_locale: "en-IN",
};

beforeEach(() => {
  vi.mocked(api.getOrganization).mockReset().mockResolvedValue(PROFILE);
  vi.mocked(api.updateOrganization)
    .mockReset()
    .mockImplementation(async (changes) => ({ ...PROFILE, ...changes }) as api.OrganizationProfile);
});

describe("OrganizationForm", () => {
  it("saves only what changed, once something has", async () => {
    const user = userEvent.setup();
    renderAdmin(<OrganizationForm />);
    const name = await screen.findByLabelText("Organisation name");
    const save = screen.getByRole("button", { name: "Save profile" });
    expect(save).toBeDisabled();

    await user.clear(name);
    await user.type(name, "Acme Talent India");
    await user.type(screen.getByLabelText("Website"), "https://acme.example");
    await user.click(save);

    await waitFor(() =>
      expect(api.updateOrganization).toHaveBeenCalledWith({
        name: "Acme Talent India",
        website: "https://acme.example",
      }),
    );
  });

  it("shows the short name without letting it change", async () => {
    renderAdmin(<OrganizationForm />);
    expect(await screen.findByLabelText("Short name")).toHaveAttribute("readonly");
  });

  it("names the country and keeps the current time zone selectable", async () => {
    renderAdmin(<OrganizationForm />);
    expect(await screen.findByRole("combobox", { name: "Country" })).toHaveTextContent("India");
    expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveTextContent("Asia/Kolkata");
  });
});
