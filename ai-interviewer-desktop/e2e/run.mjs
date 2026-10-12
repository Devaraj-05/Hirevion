// `pnpm --filter @hirevion/ai-interviewer-desktop e2e [-- --skip-build]`
//
// Runs the end-to-end test against the DEBUG build of the app on its stub backend:
//   1. builds the debug app with the webview embedded (skip with --skip-build; a plain
//      `cargo build` exe loads the dev server instead, so it is never reused);
//   2. finds msedgedriver for the installed WebView2 runtime, downloading it once;
//   3. starts `tauri-driver` (install once: `cargo install tauri-driver --locked`);
//   4. runs e2e/desktop.e2e.mjs, then stops the driver.
//
// Debug builds keep the WEBVIEW2_* variables (release builds remove them, ADR-0018), which is
// how the fake camera and microphone get in.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ensureEdgeDriver } from "./edge-driver.mjs";

const appRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const application = join(appRoot, "src-tauri", "target", "debug", "AI-Interview.exe");
const PORT = process.env.HV_E2E_PORT ?? "4444";

function fail(message) {
  console.error(`\ne2e: ${message}`);
  process.exit(1);
}

function findTauriDriver() {
  if (process.env.TAURI_DRIVER) return process.env.TAURI_DRIVER;
  const installed = join(homedir(), ".cargo", "bin", "tauri-driver.exe");
  return existsSync(installed) ? installed : "tauri-driver";
}

if (process.platform !== "win32") fail("the desktop app runs on Windows only.");

if (!process.argv.includes("--skip-build") || !existsSync(application)) {
  console.log("Building the debug app (the webview is embedded; no installer)…");
  const cli = createRequire(import.meta.url).resolve("@tauri-apps/cli/tauri.js");
  const built = spawnSync(process.execPath, [cli, "build", "--debug", "--no-bundle"], {
    cwd: appRoot,
    stdio: "inherit",
    // The updater needs no key here: nothing is bundled.
    env: { ...process.env, CI: "true" },
  });
  if (built.status !== 0) fail("the debug build failed");
}

const nativeDriver = await ensureEdgeDriver();
console.log(`msedgedriver: ${nativeDriver}`);

const env = {
  ...process.env,
  HV_DESKTOP_STUB: "1",
  HV_DESKTOP_STUB_NATIVE: "1",
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:
    "--use-fake-device-for-media-stream --use-fake-ui-for-media-stream",
  HV_E2E_APP: application,
  HV_E2E_PORT: PORT,
};

const driver = spawn(findTauriDriver(), ["--port", PORT, "--native-driver", nativeDriver], {
  env,
  stdio: ["ignore", "inherit", "inherit"],
});
driver.on("error", (error) => fail(`couldn't start tauri-driver (${error.message}).`));

async function waitForDriver() {
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/status`);
      if (response.ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  fail("tauri-driver didn't start listening");
}

function stopDriver() {
  // Also stops msedgedriver and the app, which are its children.
  spawnSync("taskkill", ["/PID", String(driver.pid), "/T", "/F"], { stdio: "ignore" });
}

let status = 1;
try {
  await waitForDriver();
  status =
    spawnSync(process.execPath, ["--test", join(appRoot, "e2e", "desktop.e2e.mjs")], {
      cwd: appRoot,
      env,
      stdio: "inherit",
    }).status ?? 1;
} finally {
  stopDriver();
}
process.exit(status);
