/**
 * The one page before the interview (product owner, 2026-11-16): camera and microphone, the
 * system check, the Terms and Conditions, then the phone, each opening once the one before it
 * is done, and Start once all of them are.
 */

export type StepId = "devices" | "checks" | "terms" | "phone";
export type StepState = "done" | "active" | "locked";
export type PhoneMode = "off" | "optional" | "required";

/** What the candidate has finished. `phone` is also true for an optional phone they skipped. */
export type Done = Record<StepId, boolean>;

const ORDER: readonly StepId[] = ["devices", "checks", "terms", "phone"];

export function steps(done: Done, phone: PhoneMode): { id: StepId; state: StepState }[] {
  const shown = ORDER.filter((id) => id !== "phone" || phone !== "off");
  let open = false;
  return shown.map((id) => {
    if (!open && done[id]) return { id, state: "done" };
    if (open) return { id, state: "locked" };
    open = true;
    return { id, state: "active" };
  });
}

export function readyToStart(done: Done, phone: PhoneMode): boolean {
  return steps(done, phone).every((step) => step.state === "done");
}
