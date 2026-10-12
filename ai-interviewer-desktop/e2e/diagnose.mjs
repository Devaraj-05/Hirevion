// Why won't the app come up under the driver? Run after a failed e2e (CI does, `if: failure()`):
//   node e2e/diagnose.mjs
// It prints, in collapsible CI groups: the Windows and WebView2 versions, what the app does when
// started directly for about 20 s (output, exit code, whether WebView2 serves a DevTools page),
// the app's data folder, and recent Windows application-error events (crashes, side-by-side
// manifest problems, missing DLLs).
import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { homedir, release, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { powershell } from "../scripts/powershell.mjs";
import { stopProcessTree } from "./driver.mjs";
import { ensureEdgeDriver, webview2Version } from "./edge-driver.mjs";

const appRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const application = join(appRoot, "src-tauri", "target", "debug", "AI-Interview.exe");
const dataDir = join(
  process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"),
  "com.hirevion.interview",
);
const DEBUG_PORT = 9223;
const WATCH_MS = 20_000;

async function group(title, run) {
  console.log(`::group::${title}`);
  try {
    await run();
  } catch (error) {
    console.log(`(this section failed: ${error.message})`);
  }
  console.log("::endgroup::");
}

function tail(text, lines) {
  return text.split(/\r?\n/).slice(-lines).join("\n");
}

function listTree(folder, depth = 0, maxDepth = 3) {
  if (!existsSync(folder)) return console.log(`${"  ".repeat(depth)}(missing) ${folder}`);
  for (const name of readdirSync(folder).sort()) {
    const path = join(folder, name);
    const info = statSync(path);
    console.log(`${"  ".repeat(depth)}${name}${info.isDirectory() ? "/" : `  ${info.size} bytes`}`);
    if (info.isDirectory() && depth < maxDepth) listTree(path, depth + 1, maxDepth);
  }
}

await group("Windows and WebView2", async () => {
  console.log(`Windows release ${release()}`);
  console.log(`WebView2 runtime ${webview2Version()}`);
  console.log(`app exists: ${existsSync(application)} (${application})`);
  const result = powershell(
    [
      "$PSVersionTable.PSVersion.ToString()",
      "whoami",
      "'session: ' + $env:SESSIONNAME",
      "(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) -join ', '",
      "(Get-CimInstance Win32_ComputerSystem).Model",
      "(Get-Process -Name msedge, msedgewebview2, msedgedriver, tauri-driver, AI-Interview -ErrorAction SilentlyContinue | ForEach-Object { $_.ProcessName + ' ' + $_.Id }) -join '; '",
    ].join("; "),
  );
  console.log(result.stdout || result.stderr);
});

await group("Starting the app directly for 20 s (stub backend, DevTools on)", async () => {
  const env = {
    ...process.env,
    HV_DESKTOP_STUB: "1",
    HV_DESKTOP_STUB_NATIVE: "1",
    RUST_LOG: "debug",
    RUST_BACKTRACE: "full",
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${DEBUG_PORT} --use-fake-device-for-media-stream --use-fake-ui-for-media-stream --enable-logging --v=1`,
  };
  let output = "";
  const started = Date.now();
  const child = spawn(application, [], { env, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout.on("data", (chunk) => (output += chunk));
  child.stderr.on("data", (chunk) => (output += chunk));
  let ended = null;
  child.once(
    "exit",
    (code, signal) => (ended = `exit code ${code ?? signal} after ${Date.now() - started} ms`),
  );
  child.once("error", (error) => (ended = `couldn't start: ${error.message}`));

  // Poll the DevTools endpoint WebView2 serves once the page exists.
  let pages = "no answer from the DevTools port";
  for (let waited = 0; waited < WATCH_MS && !ended; waited += 1000) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
      pages = `DevTools answered after ~${waited + 1000} ms: ${(await response.text()).slice(0, 800)}`;
      break;
    } catch {
      // not up yet
    }
  }
  console.log(ended ?? "the app is still running");
  console.log(pages);
  // What the app started, and whether it has a window (a hang before the webview shows here).
  const processes = powershell(
    "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'AI-Interview.exe' -or $_.CommandLine -match 'webview-exe-name=AI-Interview' } | ForEach-Object { '' + $_.ProcessId + ' <- ' + $_.ParentProcessId + ' ' + $_.Name + ' ' + ($_.CommandLine -replace '\\s+', ' ').Substring(0, [Math]::Min(260, $_.CommandLine.Length)) }; Get-Process AI-Interview -ErrorAction SilentlyContinue | ForEach-Object { 'AI-Interview window=' + $_.MainWindowHandle + ' title=' + $_.MainWindowTitle + ' responding=' + $_.Responding + ' threads=' + $_.Threads.Count }",
  );
  console.log(`--- processes ---\n${processes.stdout || processes.stderr}`);
  stopProcessTree(child);
  console.log("--- app output (last 80 lines) ---");
  console.log(tail(output, 80) || "(none)");
});

await group("msedgedriver, verbose: how it launches the app", async () => {
  const log = join(tmpdir(), "msedgedriver-verbose.log");
  const driver = spawn(
    await ensureEdgeDriver(),
    ["--port=9516", "--verbose", `--log-path=${log}`],
    {
      stdio: "ignore",
    },
  );
  try {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const response = await fetch("http://127.0.0.1:9516/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        capabilities: {
          alwaysMatch: {
            browserName: "webview2",
            "ms:edgeOptions": { binary: application, webviewOptions: {} },
          },
        },
      }),
      signal: AbortSignal.timeout(45_000),
    }).catch((error) => ({ text: async () => `no answer: ${error.message}` }));
    console.log(`session answer: ${(await response.text()).slice(0, 500)}`);
  } finally {
    stopProcessTree(driver);
  }
  if (existsSync(log)) {
    const lines = readFileSync(log, "utf8").split(/\r?\n/);
    const interesting = lines.filter((line) =>
      /WEBVIEW2|DevTools|launch|user-data|binary|args|command|port|Starting|error|fail/i.test(line),
    );
    console.log("--- msedgedriver log (relevant lines, last 60) ---");
    console.log(
      interesting
        .slice(-60)
        .map((line) => line.slice(0, 600))
        .join("\n"),
    );
  }
});

await group("The app's data folder", async () => {
  listTree(dataDir, 0, 1);
  console.log("--- WebView2 crash reports ---");
  listTree(join(dataDir, "EBWebView", "Crashpad", "reports"), 0, 0);
  for (const log of ["EBWebView/chrome_debug.log", "EBWebView/Default/chrome_debug.log"]) {
    const path = join(dataDir, log);
    if (existsSync(path)) {
      console.log(`--- ${path} (last 60 lines) ---`);
      console.log(tail(readFileSync(path, "utf8"), 60));
    }
  }
  const dumps = join(process.env.LOCALAPPDATA ?? "", "CrashDumps");
  console.log("--- CrashDumps ---");
  listTree(dumps, 0, 0);
});

await group("Recent Windows application errors", async () => {
  const result = powershell(
    "Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = (Get-Date).AddMinutes(-30) } -ErrorAction SilentlyContinue | Where-Object { $_.ProviderName -match 'Application Error|Windows Error Reporting|SideBySide|Application Hang|\\.NET Runtime|Edge|WebView2' -or $_.LevelDisplayName -eq 'Error' } | Select-Object -First 12 | ForEach-Object { '[' + $_.TimeCreated.ToString('HH:mm:ss') + '] ' + $_.ProviderName + ' (' + $_.Id + '): ' + ($_.Message -replace '\\s+', ' ').Substring(0, [Math]::Min(500, $_.Message.Length)) }",
  );
  console.log(result.stdout || result.stderr || "(no events)");
});
