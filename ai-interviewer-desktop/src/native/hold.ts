import { getCurrentWindow } from "@tauri-apps/api/window";
import { commands } from "./commands";

/**
 * A switch that is on for as long as something holds it: fullscreen for the interview (PRD
 * §31) and the app's close guard. Letting go switches it off a moment later, unless something
 * takes hold again first: React's StrictMode mounts, unmounts and remounts each effect, which
 * used to switch the window fullscreen, windowed and fullscreen again as the interview opened
 * (2026-11-25), and could have left the close guard off had its two calls arrived out of
 * order.
 */
export function switchHolder(
  set: (on: boolean) => Promise<unknown>,
  leaveAfterMs = 150,
): () => () => void {
  let holders = 0;
  let leaving: ReturnType<typeof setTimeout> | undefined;
  const apply = (on: boolean) => void set(on).catch(() => undefined);
  return () => {
    holders += 1;
    if (leaving !== undefined) {
      clearTimeout(leaving);
      leaving = undefined;
    } else if (holders === 1) {
      apply(true);
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      holders -= 1;
      if (holders > 0) return;
      leaving = setTimeout(() => {
        leaving = undefined;
        apply(false);
      }, leaveAfterMs);
    };
  };
}

/** The app window's fullscreen hold. */
export const holdFullscreen = switchHolder((on) => getCurrentWindow().setFullscreen(on));

/** The app's close guard (src-tauri close_guard.rs): closing asks the page while held. */
export const holdCloseGuard = switchHolder((on) => commands.closeGuardLive(on));
