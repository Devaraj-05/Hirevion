import { ApiProblem } from "@hirevion/api-client";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stepUp } from "@/auth/api";
import { renderWithIntl } from "@/test/render";
import { StepUpProvider, useStepUp } from "./step-up";

// Dialogs typed into by userEvent take longer than the default 5 s when the whole suite runs.
vi.setConfig({ testTimeout: 15_000 });

vi.mock("@/auth/api", () => ({ stepUp: vi.fn() }));

function problem(code: string, status = 403) {
  return new ApiProblem({ type: `urn:hirevion:problem:${code}`, title: code, status, code });
}

/** A button that runs `call` through step-up and shows what came of it. */
function Harness({ call }: { call: () => Promise<string> }) {
  const withStepUp = useStepUp();
  const [outcome, setOutcome] = useState("");
  return (
    <>
      <button
        type="button"
        onClick={() =>
          withStepUp(call).then(setOutcome, (error: unknown) =>
            setOutcome(error instanceof ApiProblem ? `refused: ${error.code}` : "failed"),
          )
        }
      >
        Change roles
      </button>
      <output>{outcome}</output>
    </>
  );
}

function setup(call: () => Promise<string>) {
  const user = userEvent.setup();
  renderWithIntl(
    <StepUpProvider>
      <Harness call={call} />
    </StepUpProvider>,
  );
  return user;
}

beforeEach(() => {
  vi.mocked(stepUp).mockReset();
});

describe("step-up", () => {
  it("asks for the password once, then retries the change", async () => {
    const call = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(problem("step-up-required"))
      .mockResolvedValueOnce("saved");
    vi.mocked(stepUp).mockResolvedValue({ ok: true });
    const user = setup(call);

    await user.click(screen.getByRole("button", { name: "Change roles" }));
    const dialog = await screen.findByRole("dialog", { name: "Confirm your password" });
    expect(dialog).toBeInTheDocument();
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
    expect(stepUp).toHaveBeenCalledWith("correct horse battery staple");
    expect(call).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the dialog open after a wrong password", async () => {
    vi.mocked(stepUp).mockResolvedValue({ ok: false, reason: "wrong" });
    const user = setup(() => Promise.reject(problem("step-up-required")));

    await user.click(screen.getByRole("button", { name: "Change roles" }));
    await user.type(await screen.findByLabelText("Password"), "not my password");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("That password is incorrect.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("says how long to wait when locked out", async () => {
    vi.mocked(stepUp).mockResolvedValue({ ok: false, reason: "locked", retryAfter: 60 });
    const user = setup(() => Promise.reject(problem("step-up-required")));

    await user.click(screen.getByRole("button", { name: "Change roles" }));
    await user.type(await screen.findByLabelText("Password"), "not my password");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(
      await screen.findByText("Too many attempts. Try again in 1 minute."),
    ).toBeInTheDocument();
  });

  it("gives the original refusal back when cancelled", async () => {
    const user = setup(() => Promise.reject(problem("step-up-required")));
    await user.click(screen.getByRole("button", { name: "Change roles" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("refused: step-up-required"),
    );
    expect(stepUp).not.toHaveBeenCalled();
  });

  it("lets other refusals through untouched", async () => {
    const user = setup(() => Promise.reject(problem("forbidden")));
    await user.click(screen.getByRole("button", { name: "Change roles" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("refused: forbidden"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
