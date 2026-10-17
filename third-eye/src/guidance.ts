/**
 * Camera permission guidance for the two browsers the third eye supports (PRD §52): iOS
 * Safari 16.4+ (the first with Wake Lock) and Android Chrome. Other browsers are tried, with
 * general advice.
 */

export type BrowserKind = "ios-safari" | "ios-other" | "android-chrome" | "android-other" | "other";

export interface Browser {
  kind: BrowserKind;
  /** iOS's version (major, minor), when it's an iPhone or iPad. */
  ios: [number, number] | null;
  /** False for iOS before 16.4, whose Safari can't keep the screen on. */
  supported: boolean;
}

const IOS = /(?:iPhone|iPad|iPod).*? OS (\d+)_(\d+)/;

export function detectBrowser(userAgent: string): Browser {
  const ios = IOS.exec(userAgent);
  if (ios) {
    const version: [number, number] = [Number(ios[1]), Number(ios[2])];
    const safari = !/CriOS|FxiOS|EdgiOS|OPiOS/.test(userAgent);
    const supported = version[0] > 16 || (version[0] === 16 && version[1] >= 4);
    return { kind: safari ? "ios-safari" : "ios-other", ios: version, supported };
  }
  if (/Android/.test(userAgent)) {
    const chrome = /Chrome\//.test(userAgent) && !/SamsungBrowser|EdgA|OPR|Firefox/.test(userAgent);
    return { kind: chrome ? "android-chrome" : "android-other", ios: null, supported: true };
  }
  return { kind: "other", ios: null, supported: true };
}

export type PermissionState = "prompt" | "denied";

/** What to tell the candidate, before the browser asks or after they refused. */
export function cameraHelp(browser: Browser, state: PermissionState): string[] {
  const lines: string[] = [];
  if (!browser.supported) {
    lines.push(
      "This iPhone runs an iOS version before 16.4, which can't keep the camera running. Update iOS, or use another phone.",
    );
  }
  if (state === "prompt") {
    lines.push(
      "Your phone will ask to use the camera. Tap Allow: the camera's picture goes only to this interview.",
    );
    if (browser.kind === "ios-other") {
      lines.push("If nothing happens, open this link in Safari instead.");
    }
    return lines;
  }
  switch (browser.kind) {
    case "ios-safari":
    case "ios-other":
      lines.push(
        "Tap the aA button in the address bar, then Website Settings, and set Camera to Allow.",
        "If Camera isn't listed, open Settings > Safari > Camera and choose Ask or Allow.",
        "Then reload this page.",
      );
      break;
    case "android-chrome":
      lines.push(
        "Tap the lock icon next to the address, then Permissions, and turn Camera on.",
        "If it stays off, open Settings > Apps > Chrome > Permissions > Camera and allow it.",
        "Then reload this page.",
      );
      break;
    default:
      lines.push(
        "Allow this page to use the camera in your browser's site settings, then reload it.",
        "On iPhone, Safari works best; on Android, Chrome.",
      );
  }
  return lines;
}
