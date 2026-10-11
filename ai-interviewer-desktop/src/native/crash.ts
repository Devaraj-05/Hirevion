import { commands } from "./commands";

/**
 * Webview errors go to Rust (`crash_report`), which scrubs them and sends them to GlitchTip when
 * the build has a DSN. The webview never contacts GlitchTip itself, so the CSP stays shut
 * (ADR-0019). Rust also truncates and caps what it takes; this keeps the payload small first.
 */

export interface WebviewError {
  kind: "error" | "unhandledrejection";
  message: string;
  stack: string | null;
}

const MAX_MESSAGE = 2_000;
const MAX_STACK = 6_000;

/** A value thrown or rejected, as a message and a stack. */
export function describeError(kind: WebviewError["kind"], value: unknown): WebviewError {
  let message: string;
  let stack: string | null = null;
  if (value instanceof Error) {
    message = `${value.name}: ${value.message}`;
    stack = value.stack ?? null;
  } else if (typeof value === "string") {
    message = value;
  } else {
    try {
      message = JSON.stringify(value) ?? String(value);
    } catch {
      message = String(value);
    }
  }
  return {
    kind,
    message: message.slice(0, MAX_MESSAGE),
    stack: stack ? stack.slice(0, MAX_STACK) : null,
  };
}

/** Reports uncaught errors and unhandled promise rejections. Returns nothing to undo. */
export function installCrashReporting(
  target: Pick<Window, "addEventListener"> = window,
  send: (error: WebviewError) => Promise<unknown> = commands.crashReport,
) {
  const report = (error: WebviewError) => {
    // A failing report must never raise another error.
    send(error).catch(() => undefined);
  };
  target.addEventListener("error", (event) => {
    report(describeError("error", event.error ?? event.message));
  });
  target.addEventListener("unhandledrejection", (event) => {
    report(describeError("unhandledrejection", event.reason));
  });
}
