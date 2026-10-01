import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { signIn } from "@/auth/api";
import { renderWithIntl } from "@/test/render";
import { LoginForm } from "./login-form";

vi.mock("@/auth/api", () => ({ signIn: vi.fn() }));

beforeEach(() => {
  vi.mocked(signIn).mockReset();
});

async function submit(next: string, onSignedIn = vi.fn()) {
  const user = userEvent.setup();
  renderWithIntl(<LoginForm next={next} onSignedIn={onSignedIn} />);
  await user.type(screen.getByLabelText("Email"), "ravi@acme.example.test");
  await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return onSignedIn;
}

describe("LoginForm", () => {
  it("goes to the page the visitor wanted once signed in", async () => {
    vi.mocked(signIn).mockResolvedValue({ ok: true });
    const onSignedIn = await submit("/jobs?status=open");
    expect(signIn).toHaveBeenCalledWith("ravi@acme.example.test", "correct horse battery staple");
    expect(onSignedIn).toHaveBeenCalledWith("/jobs?status=open");
  });

  it("never sends the visitor off the site", async () => {
    vi.mocked(signIn).mockResolvedValue({ ok: true });
    const onSignedIn = await submit("https://evil.example");
    expect(onSignedIn).toHaveBeenCalledWith("/dashboard");
  });

  it("says when the email or password is wrong, and moves focus to the message", async () => {
    vi.mocked(signIn).mockResolvedValue({ ok: false, reason: "invalid" });
    const onSignedIn = await submit("/dashboard");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Email or password is incorrect.");
    expect(alert).toHaveFocus();
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("says how long to wait after too many attempts", async () => {
    vi.mocked(signIn).mockResolvedValue({ ok: false, reason: "locked", retryAfter: 120 });
    await submit("/dashboard");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Too many attempts. Try again in 2 minutes.",
    );
  });

  it("checks the fields before calling the API", async () => {
    const user = userEvent.setup();
    renderWithIntl(<LoginForm next="/dashboard" onSignedIn={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(signIn).not.toHaveBeenCalled();
  });
});
