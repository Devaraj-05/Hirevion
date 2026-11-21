import type { AppsToClose } from "../native/commands";

/**
 * What the apps check before Start asks of the candidate (owner, 2026-11-21: "ask the candidate
 * to close all the background and other applications"; ADR-0046): an app the interview's policy
 * blocks, showing a window, must be closed before Start. A blocked one without a window (a
 * service the candidate may not be able to stop) and other open apps are advised closed.
 * `null`: the interview doesn't check apps. `"failed"`: the look didn't work, so the candidate
 * is asked to close apps themselves (the monitor still reports during the interview).
 */
export type AppsVerdict = "close" | "advise" | "clear";

export function appsVerdict(apps: AppsToClose | "failed" | null): AppsVerdict {
  if (apps === null) return "clear";
  if (apps === "failed") return "advise";
  if (apps.blocked.length > 0) return "close";
  return apps.background.length > 0 || apps.open.length > 0 ? "advise" : "clear";
}
