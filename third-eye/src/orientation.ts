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
  try {
    if (!doc.fullscreenElement && doc.documentElement.requestFullscreen) {
      await doc.documentElement.requestFullscreen();
    }
    await orientation.lock.call(orientation, "landscape");
    return "locked";
  } catch {
    return "refused";
  }
}
