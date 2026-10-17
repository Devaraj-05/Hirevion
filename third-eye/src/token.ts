/**
 * The pairing token from the page's URL fragment (`#t=...`). The fragment never leaves the
 * phone, so the token stays out of server and proxy logs.
 */
export function readToken(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("t");
  return token ? token : null;
}

/** Automated tests add `auto=1` to start the camera without a tap. */
export function wantsAutoStart(hash: string): boolean {
  return new URLSearchParams(hash.replace(/^#/, "")).get("auto") === "1";
}

const DEVICE_KEY = "hv-third-eye-device";

/**
 * The device secret `redeem` answers, kept for this tab only (sessionStorage) so a reload or a
 * long lock can rejoin without a new QR code. Storage can be unavailable (private browsing).
 */
export function rememberDevice(storage: Storage | undefined, secret: string | null): void {
  try {
    if (secret) storage?.setItem(DEVICE_KEY, secret);
  } catch {
    // Without storage, a reload needs a new QR code; streaming still works.
  }
}

export function recallDevice(storage: Storage | undefined): string | null {
  try {
    return storage?.getItem(DEVICE_KEY) ?? null;
  } catch {
    return null;
  }
}
