import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/render";
import { portalForgotPassword, portalSetPassword, portalSignIn } from "./api";
import { PortalForgotForm, PortalLoginForm, PortalPasswordForm } from "./forms";

vi.mock("./api", () => ({
  portalSignIn: vi.fn(),
  portalForgotPassword: vi.fn(),
  portalSetPassword: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(portalSignIn).mockReset();
  vi.mocked(portalForgotPassword).mockReset();
  vi.mocked(portalSetPassword).mockReset();
});

const PASSWORD = "twelve chars ok";

describe("PortalLoginForm", () => {
  async function submit(next: string, onSignedIn = vi.fn()) {
    const user = userEvent.setup();
    renderWithIntl(<PortalLoginForm next={next} onSignedIn={onSignedIn} />);
    await user.type(screen.getByLabelText("Email"), "asha@example.test");
    await user.type(screen.getByLabelText("Password"), PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    return onSignedIn;
  }

  it("signs in to the portal and goes where the candidate was going", async () => {
    vi.mocked(portalSignIn).mockResolvedValue({ ok: true });
    const onSignedIn = await submit("/requests");
    expect(portalSignIn).toHaveBeenCalledWith("asha@example.test", PASSWORD);
    expect(onSignedIn).toHaveBeenCalledWith("/requests");
  });

  it("never leaves the portal", async () => {
    vi.mocked(portalSignIn).mockResolvedValue({ ok: true });
    expect(await submit("//evil.example")).toHaveBeenCalledWith("/");
  });

  it("says when the email or password is wrong", async () => {
    vi.mocked(portalSignIn).mockResolvedValue({ ok: false, reason: "invalid" });
    await submit("/");
    expect(screen.getByRole("alert")).toHaveTextContent("Email or password is incorrect.");
  });
});

describe("PortalPasswordForm", () => {
  async function fill(password: string, confirmation = password) {
    const user = userEvent.setup();
    const onDone = vi.fn();
    renderWithIntl(<PortalPasswordForm mode="set" token="abc" onDone={onDone} />);
    await user.type(screen.getByLabelText("New password"), password);
    await user.type(screen.getByLabelText("Confirm the new password"), confirmation);
    await user.click(screen.getByRole("button", { name: "Set the password" }));
    return onDone;
  }

  it("needs 12 characters, not the recruiters' 15", async () => {
    vi.mocked(portalSetPassword).mockResolvedValue({ ok: true });
    await fill("short");
    expect(await screen.findByText("Use at least 12 characters.")).toBeVisible();
    expect(portalSetPassword).not.toHaveBeenCalled();
  });

  it("sets the first password from the invitation and goes to sign in", async () => {
    vi.mocked(portalSetPassword).mockResolvedValue({ ok: true });
    const onDone = await fill(PASSWORD);
    expect(portalSetPassword).toHaveBeenCalledWith("set", "abc", PASSWORD);
    expect(onDone).toHaveBeenCalledWith("/login?set=1");
  });

  it("shows the API's reasons and an expired link", async () => {
    vi.mocked(portalSetPassword).mockResolvedValueOnce({
      ok: false,
      reason: "rejected",
      codes: ["breached"],
    });
    await fill(PASSWORD);
    expect(await screen.findByText(/appeared in a data breach/)).toBeVisible();
  });

  it("offers a new link when the old one has expired", async () => {
    vi.mocked(portalSetPassword).mockResolvedValue({ ok: false, reason: "expired" });
    await fill(PASSWORD);
    expect(screen.getByRole("link", { name: "Ask for a new link" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });
});

describe("PortalForgotForm", () => {
  it("answers the same whether or not the account exists", async () => {
    vi.mocked(portalForgotPassword).mockResolvedValue("sent");
    const user = userEvent.setup();
    renderWithIntl(<PortalForgotForm />);
    await user.type(screen.getByLabelText("Email"), "asha@example.test");
    await user.click(screen.getByRole("button", { name: "Send the link" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "If an account exists for asha@example.test, we've emailed it a link.",
    );
  });
});
