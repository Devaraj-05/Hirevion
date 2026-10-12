// Finds msedgedriver.exe for the installed WebView2 runtime, downloading the matching one once.
// The driver must match the runtime's version; a stale driver is the usual cause of "session not
// created". Override with MSEDGEDRIVER=<path to msedgedriver.exe>.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { expandArchive } from "../scripts/powershell.mjs";

const WEBVIEW2_RUNTIME = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
const KEYS = [
  `HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\${WEBVIEW2_RUNTIME}`,
  `HKLM\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\${WEBVIEW2_RUNTIME}`,
  `HKCU\\Software\\Microsoft\\EdgeUpdate\\Clients\\${WEBVIEW2_RUNTIME}`,
];

export function webview2Version() {
  for (const key of KEYS) {
    const result = spawnSync("reg", ["query", key, "/v", "pv"], { encoding: "utf8" });
    const match = /pv\s+REG_SZ\s+(\d+\.\d+\.\d+\.\d+)/.exec(result.stdout ?? "");
    if (match) return match[1];
  }
  throw new Error("WebView2 Runtime isn't installed (no EdgeUpdate registry entry).");
}

export async function ensureEdgeDriver() {
  if (process.env.MSEDGEDRIVER) {
    if (!existsSync(process.env.MSEDGEDRIVER)) {
      throw new Error(`MSEDGEDRIVER=${process.env.MSEDGEDRIVER} doesn't exist`);
    }
    return process.env.MSEDGEDRIVER;
  }
  const version = webview2Version();
  const folder = join(homedir(), ".hirevion", "msedgedriver", version);
  const exe = join(folder, "msedgedriver.exe");
  if (existsSync(exe)) return exe;

  const archive = process.arch === "arm64" ? "edgedriver_arm64.zip" : "edgedriver_win64.zip";
  const url = `https://msedgedriver.microsoft.com/${version}/${archive}`;
  console.log(`Downloading ${url}`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url}: ${response.status}. Set MSEDGEDRIVER to a matching msedgedriver.exe.`);
  }
  mkdirSync(folder, { recursive: true });
  const zip = join(folder, archive);
  writeFileSync(zip, Buffer.from(await response.arrayBuffer()));
  try {
    expandArchive(zip, folder);
  } finally {
    rmSync(zip, { force: true });
  }
  if (!existsSync(exe))
    throw new Error(`${archive} has no msedgedriver.exe (unpacked into ${folder})`);
  return exe;
}
