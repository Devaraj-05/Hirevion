import { getCurrentWindow } from "@tauri-apps/api/window";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { commands } from "../native/commands";
import { describeError } from "../native/crash";
import { PillButton } from "./kit";

/**
 * The app's last line (2026-11-26): a screen that throws while rendering used to leave a blank
 * window. This shows a way out instead, reports the error like any other, and never depends on
 * the app's state or translations (it sits above them; both locales are English).
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo) {
    const report = describeError("error", error);
    const stack = [report.stack, info.componentStack].filter(Boolean).join("\n");
    commands.crashReport({ ...report, stack: stack || null }).catch(() => undefined);
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="app-ground grid min-h-dvh place-items-center p-6">
        <section
          aria-labelledby="crash-title"
          className="grid max-w-md gap-4 rounded-[20px] border border-border/70 bg-surface p-8 text-center shadow-[var(--shadow-md)]"
        >
          <h1 id="crash-title" className="font-semibold text-[1.35rem] leading-tight">
            This screen stopped working
          </h1>
          <p className="text-muted-foreground leading-relaxed">
            Reload to carry on where you were. If you were in your interview, you can rejoin it once
            within two minutes.
          </p>
          <div className="flex justify-center gap-3">
            <PillButton variant="secondary" onClick={() => void getCurrentWindow().destroy()}>
              Close app
            </PillButton>
            <PillButton onClick={() => window.location.reload()}>Reload</PillButton>
          </div>
        </section>
      </main>
    );
  }
}
