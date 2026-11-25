/**
 * Ending the interview (End Interview, the window's close, or the interviewer's goodbye). Each
 * step has a time limit, so one that hangs can't keep the candidate in an interview they
 * ended: on 2026-11-25 End Interview did nothing while the monitoring was stuck.
 */
export interface EndingSteps {
  /** Saves the workspaces' unsaved text (a save after `complete` is refused). */
  flush(): Promise<unknown>;
  /** Stops the monitoring and the recording; their segments upload afterwards. */
  stopServices(): Promise<unknown>;
  /** Tells the server the interview ended. */
  complete(): Promise<unknown>;
  /** Leaves the voice room. */
  disconnect(): Promise<unknown>;
}

// A late `complete` still ends the interview: the candidate leaves the room, and the server
// completes it as "left early" once the reconnect window passes (C8-9), so nothing is lost.
export const ENDING_LIMITS_MS = {
  flush: 8_000,
  stopServices: 8_000,
  complete: 15_000,
  disconnect: 2_000,
};

class StepTimedOut extends Error {
  constructor(step: string) {
    super(`${step} took too long`);
    this.name = "StepTimedOut";
  }
}

function bounded(step: string, work: Promise<unknown>, ms: number): Promise<unknown> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new StepTimedOut(step)), ms);
  });
  return Promise.race([work, late]).finally(() => clearTimeout(timer));
}

/** Runs the steps in order. Only a failed `complete` is reported; the rest end regardless. */
export async function endInterview(
  steps: EndingSteps,
  onCompleteFailed: (error: unknown) => void,
  limits = ENDING_LIMITS_MS,
): Promise<void> {
  await bounded("flush", steps.flush(), limits.flush).catch(() => undefined);
  await bounded("stopServices", steps.stopServices(), limits.stopServices).catch(() => undefined);
  try {
    await bounded("complete", steps.complete(), limits.complete);
  } catch (error) {
    onCompleteFailed(error);
  }
  await bounded("disconnect", steps.disconnect(), limits.disconnect).catch(() => undefined);
}
