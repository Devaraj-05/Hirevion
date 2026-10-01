import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { requestPasswordReset } from "@/auth/api";
import { renderWithIntl } from "@/test/render";
import { ForgotPasswordForm } from "./forgot-password-form";

vi.mock("@/auth/api", () => ({ requestPasswordReset: vi.fn() }));

beforeEach(() => {
  vi.mocked(requestPasswordReset).mockReset();
});

async function ask(email: string) {
  const user = userEvent.setup();
  renderWithIntl(<ForgotPasswordForm />);
  await user.type(screen.getByLabelText("Email"), email);
  await user.click(screen.getByRole("button", { name: "Send the link" }));
}

describe("ForgotPasswordForm", () => {
  it("confirms without saying whether the account exists", async () => {
    vi.mocked(requestPasswordReset).mockResolvedValue("sent");
    await ask("ravi@acme.example.test");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "If an account exists for ravi@acme.example.test, we've emailed a link to reset its password. The link expires in 30 minutes.",
    );
  });

  it("asks the visitor to wait when there have been too many requests", async () => {
    vi.mocked(requestPasswordReset).mockResolvedValue("limited");
    await ask("ravi@acme.example.test");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many requests. Try again later.",
    );
  });
});
