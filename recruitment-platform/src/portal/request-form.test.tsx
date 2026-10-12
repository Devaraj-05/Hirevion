import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/render";
import { createPortalRequest } from "./api";
import { RequestForm } from "./request-form";

vi.mock("./api", () => ({ createPortalRequest: vi.fn() }));

const INTERVIEWS = [{ id: "iv-1", label: "Backend Engineer (IV-0042)" }];

beforeEach(() => {
  vi.mocked(createPortalRequest).mockReset();
  vi.mocked(createPortalRequest).mockResolvedValue({ ok: true, reference: "RQ-1A2B3C4D" });
});

describe("RequestForm", () => {
  it("asks to reschedule a chosen interview, as the interview card links it", async () => {
    const user = userEvent.setup();
    const onSent = vi.fn();
    renderWithIntl(
      <RequestForm
        interviews={INTERVIEWS}
        initialKind="reschedule"
        initialInterview="iv-1"
        onSent={onSent}
      />,
    );
    expect(screen.getByLabelText("What do you need?")).toHaveValue("reschedule");
    expect(screen.getByLabelText("Interview")).toHaveValue("iv-1");
    await user.type(screen.getByLabelText("When would suit you?"), "After the 20th");
    await user.type(screen.getByLabelText("Details"), "I'm travelling");
    await user.click(screen.getByRole("button", { name: "Send the request" }));
    expect(createPortalRequest).toHaveBeenCalledWith({
      kind: "reschedule",
      interview_id: "iv-1",
      message: "I'm travelling",
      details: { preferred: "After the 20th" },
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Request sent.");
    expect(onSent).toHaveBeenCalled();
  });

  it("checks what each kind needs before sending", async () => {
    const user = userEvent.setup();
    renderWithIntl(<RequestForm interviews={INTERVIEWS} onSent={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("What do you need?"), "consent_withdrawal");
    await user.click(screen.getByRole("button", { name: "Send the request" }));
    expect(await screen.findByText("Choose at least one.")).toBeVisible();
    await user.click(screen.getByRole("checkbox", { name: /Camera/ }));
    await user.click(screen.getByRole("button", { name: "Send the request" }));
    expect(createPortalRequest).toHaveBeenCalledWith({
      kind: "consent_withdrawal",
      message: "",
      details: { purposes: ["camera"] },
    });
  });

  it("needs words for support and a nominee for a nomination", async () => {
    const user = userEvent.setup();
    renderWithIntl(<RequestForm interviews={INTERVIEWS} onSent={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("What do you need?"), "support");
    await user.click(screen.getByRole("button", { name: "Send the request" }));
    expect(await screen.findByText("Say what you need.")).toBeVisible();
    await user.selectOptions(screen.getByLabelText("What do you need?"), "nomination");
    await user.click(screen.getByRole("button", { name: "Send the request" }));
    expect(await screen.findByText("Give the nominee's name and email address.")).toBeVisible();
    expect(createPortalRequest).not.toHaveBeenCalled();
  });

  it("asks for adjustments with their kinds", async () => {
    const user = userEvent.setup();
    renderWithIntl(<RequestForm interviews={INTERVIEWS} onSent={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText("What do you need?"), "accommodation");
    await user.selectOptions(screen.getByLabelText("Interview"), "iv-1");
    await user.click(screen.getByRole("checkbox", { name: "Extended time" }));
    await user.click(screen.getByRole("button", { name: "Send the request" }));
    expect(createPortalRequest).toHaveBeenCalledWith({
      kind: "accommodation",
      interview_id: "iv-1",
      message: "",
      details: { kinds: ["extended_time"] },
    });
  });
});
