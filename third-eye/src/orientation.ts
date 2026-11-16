/**
 * The phone films what its page's orientation says, not how it is held: with rotation locked,
 * an Android phone turned sideways keeps sending upright frames, with the room turned in them
 * (the product owner's first preview, 2026-11-15). Locking the page itself to landscape makes
 * the camera film landscape whatever the rotation setting. Chrome on Android allows the lock
 * only in full screen and after a tap; Safari on iPhone has no lock.
 */

export type LockResult = "locked" | "unsupported" | "refused";

interface FullscreenDocument {
  fullscreenElement: Element | null;
  documentElement: { requestFullscreen?: () => Promise<void> };
  exitFullscreen?: () => Promise<void>;
}

interface LockableScreen {
  orientation?: { lock?: (to: string) => Promise<void> };
}

export async function lockLandscape(
  doc: FullscreenDocument = document,
  screen: LockableScreen = window.screen as unknown as LockableScreen,
): Promise<LockResult> {
  const orientation = screen.orientation;
  if (!orientation?.lock) return "unsupported";
  let entered = false;
  try {
    if (!doc.fullscreenElement && doc.documentElement.requestFullscreen) {
      await doc.documentElement.requestFullscreen();
      entered = true;
    }
    await orientation.lock.call(orientation, "landscape");
    return "locked";
  } catch {
    // Full screen alone gains nothing: leave it rather than strand the page there.
    if (entered) await doc.exitFullscreen?.().catch(() => undefined);
    return "refused";
  }
}

/**
 * What the phone offers while its picture is still upright. The button tries the lock again
 * (also when an earlier lock was lost, e.g. the camera prompt left full screen); once a lock
 * was tried, or can't be, the phone's own rotation setting is the other way out.
 */
export function turnAdvice(lock: LockResult | null): { button: boolean; rotationHint: boolean } {
  return { button: lock !== "unsupported", rotationHint: lock !== null };
}
