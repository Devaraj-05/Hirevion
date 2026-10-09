import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as adminApi from "@/admin/api";
import { CandidateAccessCard } from "@/admin/organization/candidate-access-card";
import { renderAdmin } from "@/test/render";
import * as api from "./api";
import { ReleasesPanel } from "./releases-panel";

vi.setConfig({ testTimeout: 20_000 });

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getReleaseRegistry: vi.fn(),
  createRelease: vi.fn(),
  updateRelease: vi.fn(),
  updateChannel: vi.fn(),
}));
vi.mock("@/admin/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/admin/api")>()),
  getCandidateAccess: vi.fn(),
  saveCandidateAccess: vi.fn(),
}));

const RELEASE: api.Release = {
  id: "r-1",
  version: "1.5.0",
  channel: "stable",
  arch: "x64",
  notes: "",
  url: "https://downloads.example/AI-Interview_1.5.0_x64-setup.nsis.zip",
  signature: "sig",
  status: "draft",
  rollout_percent: 25,
  published_at: null,
  created_at: "2026-10-09T00:00:00Z",
  updated_at: "2026-10-09T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getReleaseRegistry).mockResolvedValue({
    channels: [
      {
        channel: "stable",
        minimum_version: "1.3.0",
        download_url: "",
        updated_at: "2026-10-09T00:00:00Z",
      },
      {
        channel: "beta",
        minimum_version: "0.0.0",
        download_url: "",
        updated_at: "2026-10-09T00:00:00Z",
      },
    ],
    releases: [RELEASE],
  });
});

describe("ReleasesPanel", () => {
  it("lists the channels and releases, and publishes a draft", async () => {
    vi.mocked(api.updateRelease).mockResolvedValue({ ...RELEASE, status: "published" });
    renderAdmin(<ReleasesPanel />);
    expect(await screen.findByText("The stable channel")).toBeInTheDocument();
    expect(screen.getByDisplayValue("1.3.0")).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /1\.5\.0/ });
    expect(within(row).getByText("Draft")).toBeInTheDocument();
    expect(within(row).getByText("25%")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Publish 1.5.0" }));
    await waitFor(() =>
      expect(api.updateRelease).toHaveBeenCalledWith("r-1", { status: "published" }),
    );
  });

  it("sets a channel's minimum version", async () => {
    vi.mocked(api.updateChannel).mockResolvedValue({
      channel: "stable",
      minimum_version: "1.4.0",
      download_url: "",
      updated_at: "2026-10-09T00:00:00Z",
    });
    renderAdmin(<ReleasesPanel />);
    const minimum = (await screen.findAllByLabelText("Oldest version that may sign in"))[0];
    if (!minimum) throw new Error("no minimum field");
    await userEvent.clear(minimum);
    await userEvent.type(minimum, "1.4.0");
    await userEvent.click(
      screen.getAllByRole("button", { name: "Save the channel" })[0] as HTMLElement,
    );
    await waitFor(() =>
      expect(api.updateChannel).toHaveBeenCalledWith("stable", {
        minimum_version: "1.4.0",
        download_url: "",
      }),
    );
  });

  it("adds a release as a draft", async () => {
    vi.mocked(api.createRelease).mockResolvedValue(RELEASE);
    renderAdmin(<ReleasesPanel />);
    await userEvent.click(await screen.findByRole("button", { name: "Add a release" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Version"), "1.6.0");
    await userEvent.type(
      within(dialog).getByLabelText(/Download address/),
      "https://downloads.example/a.zip",
    );
    await userEvent.type(within(dialog).getByLabelText(/minisign signature/), "sig");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add the release" }));
    await waitFor(() =>
      expect(api.createRelease).toHaveBeenCalledWith(
        expect.objectContaining({ version: "1.6.0", channel: "stable", arch: "x64" }),
      ),
    );
  });
});

describe("CandidateAccessCard", () => {
  it("turns the new-device code off", async () => {
    vi.mocked(adminApi.getCandidateAccess).mockResolvedValue({ new_device_otp: true });
    vi.mocked(adminApi.saveCandidateAccess).mockResolvedValue({ new_device_otp: false });
    renderAdmin(<CandidateAccessCard />);
    const toggle = await screen.findByRole("switch", {
      name: "Ask for an emailed code on a new computer",
    });
    expect(toggle).toBeChecked();
    await userEvent.click(toggle);
    await waitFor(() => expect(adminApi.saveCandidateAccess).toHaveBeenCalledWith(false));
  });

  it("says when the setting didn't load, and retries", async () => {
    vi.mocked(adminApi.getCandidateAccess).mockRejectedValue(new Error("down"));
    renderAdmin(<CandidateAccessCard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("didn't load");
    vi.mocked(adminApi.getCandidateAccess).mockResolvedValue({ new_device_otp: true });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("switch")).toBeChecked();
  });
});
