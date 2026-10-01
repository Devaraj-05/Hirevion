/** A readable name for a session's device, from its user agent (best effort). */

export interface Device {
  browser: string;
  system: string;
}

// Order matters: Edge and Opera also say Chrome, and Chrome also says Safari.
const BROWSERS: readonly [RegExp, string][] = [
  [/Edg\//, "Edge"],
  [/OPR\//, "Opera"],
  [/Firefox\//, "Firefox"],
  [/Chrome\//, "Chrome"],
  [/Safari\//, "Safari"],
];

// iPhone and iPad user agents also say "Mac OS X", and Android ones say "Linux".
const SYSTEMS: readonly [RegExp, string][] = [
  [/iPhone|iPad|iPod/, "iOS"],
  [/Android/, "Android"],
  [/Windows/, "Windows"],
  [/Mac OS X|Macintosh/, "macOS"],
  [/CrOS/, "ChromeOS"],
  [/Linux/, "Linux"],
];

export function describeDevice(userAgent: string | null | undefined): Device | null {
  if (!userAgent) return null;
  const browser = BROWSERS.find(([pattern]) => pattern.test(userAgent))?.[1];
  const system = SYSTEMS.find(([pattern]) => pattern.test(userAgent))?.[1];
  return browser && system ? { browser, system } : null;
}
