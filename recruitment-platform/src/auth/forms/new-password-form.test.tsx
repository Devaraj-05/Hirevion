import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setNewPassword } from "@/auth/api";
import { renderWithIntl } from "@/test/render";
import { NewPasswordForm } from "./new-password-form";

vi.mock("@/auth/api", () => ({ setNewPassword: vi.fn() }));

const PASSWORD = "a brand new long passphrase";

beforeEach(() => {
  vi.mocked(setNewPassword).mockReset();
});

async function fill(password: string, confirmation: string, onDone = vi.fn()) {
  const user = userEvent.setup();
  renderWithIntl(<NewPasswordForm token="t0k3n" mode="reset" onDone={onDone} />);
  await user.type(screen.getByLabelText("New password"), password);
  await user.type(screen.getByLabelText("Confirm the new password"), confirmation);
  await user.click(screen.getByRole("button", { name: "Save the new password" }));
  return onDone;
}

describe("NewPasswordForm", () => {
  it("checks the two entries match before calling the API", async () => {
    await fill(PASSWORD, `${PASSWORD}!`);
    expect(await screen.findByText("The passwords don't match.")).toBeInTheDocument();
    expect(setNewPassword).not.toHaveBeenCalled();
  });

  it("shows the API's reason on the password field", async () => {
    vi.mocked(setNewPassword).mockResolvedValue({
      ok: false,
      reason: "rejected",
      problems: { password: "breached" },
    });
    await fill(PASSWORD, PASSWORD);
    expect(
      await screen.findByText(
        "This password has appeared in a data breach or is too common. Choose another.",
      ),
    ).toBeInTheDocument();
  });

  it("explains an expired link and offers a new one", async () => {
    vi.mocked(setNewPassword).mockResolvedValue({ ok: false, reason: "expired" });
    await fill(PASSWORD, PASSWORD);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This link has expired or was already used.",
    );
    expect(screen.getByRole("link", { name: "Ask for a new link" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("sends the user to sign in with the new password", async () => {
    vi.mocked(setNewPassword).mockResolvedValue({ ok: true });
    const onDone = await fill(PASSWORD, PASSWORD);
    expect(setNewPassword).toHaveBeenCalledWith("reset", "t0k3n", PASSWORD);
    expect(onDone).toHaveBeenCalledWith("/login?reset=1");
  });
});
