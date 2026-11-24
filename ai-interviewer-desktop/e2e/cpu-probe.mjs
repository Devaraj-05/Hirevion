// `pnpm --filter @hirevion/ai-interviewer-desktop e2e -- --skip-build --probe`
//
// How much CPU the app takes on the interview screen (perf investigation, 2026-11-24). It walks
// the stub backend to the interview, like desktop.e2e.mjs, then samples every process's CPU for
// HV_PROBE_SECONDS (default 20) and prints the app's processes (the Rust app and its WebView2
// processes) and the whole machine (all processes but Idle), as % of one core. Run it on a quiet
// PC. It reads Windows' English counter names, so it needs an English Windows.
import { spawnSync } from "node:child_process";
import { Session } from "./webdriver.mjs";

const SERVER = `http://127.0.0.1:${process.env.HV_E2E_PORT ?? 4444}`;
const application = process.env.HV_E2E_APP;
const SECONDS = Number(process.env.HV_PROBE_SECONDS ?? 20);
const button = (text) => `//button[normalize-space()="${text}"]`;
const heading = (text) => `//h1[normalize-space()="${text}"]`;

/** Average CPU per process name over `seconds`, as % of one core, from Windows' counters. */
function sampleCpu(seconds) {
  const script = `
$samples = Get-Counter '\\Process(*)\\% Processor Time' -SampleInterval 1 -MaxSamples ${seconds} -ErrorAction SilentlyContinue
$rows = @{}
foreach ($set in $samples) { foreach ($s in $set.CounterSamples) {
  $name = ($s.InstanceName -replace '#\\d+$','')
  if (-not $rows.ContainsKey($name)) { $rows[$name] = 0.0 }
  $rows[$name] += $s.CookedValue
} }
$invariant = [cultureinfo]::InvariantCulture
$rows.GetEnumerator() | ForEach-Object { $_.Key + "\t" + ($_.Value / ${seconds}).ToString('F1', $invariant) }`;
  const run = spawnSync("powershell.exe", ["-NoProfile", "-Command", script], {
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  return run.stdout
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      const [name, value] = line.split("\t");
      return { name, cpu: Number(value) };
    })
    .sort((a, b) => b.cpu - a.cpu);
}

const session = await Session.start(SERVER, application);
try {
  await session.waitFor(heading("Sign in to your interview"), 60_000);
  await (await session.find("input[type=email]")).type("asha@example.test");
  await (await session.find("input[type=password]")).type("stub");
  await session.click("button[type=submit]");
  await session.waitFor(heading("Your interviews"));
  await session.click(button("Get ready"));
  await session.waitFor(heading("Get ready for your interview"));
  await session.click(button("Allow access"));
  await session.waitFor(button("Continue"), 20_000);
  await session.click(button("Continue"));
  await session.waitFor(button("Yes, I heard it"), 60_000);
  await session.click(button("Yes, I heard it"));
  await session.waitFor(`//p[normalize-space()="Close these apps to continue"]`, 30_000);
  await session.click(button("Check again"));
  await session.waitFor(`//p[normalize-space()="Close your other apps"]`, 30_000);
  await session.click(button("Continue"));
  await session.waitFor(`//label[starts-with(normalize-space(), "I have read and agree")]`, 30_000);
  const [terms] = await session.findAll("button[role=checkbox]");
  await terms.click();
  await session.waitFor(`//p[starts-with(normalize-space(), "In the green zone")]`, 30_000);
  const [confirm] = await session.findAll("button[role=checkbox]");
  await confirm.click();
  await session.click(button("Confirm placement"));
  await session.waitFor(`//*[normalize-space()="You're all set."]`);
  await session.click(button("Start interview"));
  await session.waitFor(button("End Interview"), 60_000);
  // Let the services start (recording, face module, monitoring) before measuring.
  await new Promise((resolve) => setTimeout(resolve, 8_000));
  const rows = sampleCpu(SECONDS);
  // `_total` counts the Idle process too: the machine's work is the rest.
  const cpuOf = (name) => rows.find((row) => row.name === name)?.cpu ?? 0;
  const total = cpuOf("_total") - cpuOf("idle");
  const app = rows.filter((row) => /^(ai-interview|msedgewebview2)$/i.test(row.name));
  console.log(`\nInterview screen, ${SECONDS} s, % of one core (8 logical CPUs = 800%):`);
  for (const row of app) console.log(`  ${row.name.padEnd(18)} ${row.cpu.toFixed(1)}`);
  console.log(
    `  ${"app total".padEnd(18)} ${app.reduce((sum, row) => sum + row.cpu, 0).toFixed(1)}`,
  );
  console.log(`  ${"machine".padEnd(18)} ${total.toFixed(1)}`);
  console.log("\nTop processes:");
  for (const row of rows.filter((row) => !["_total", "idle"].includes(row.name)).slice(0, 8)) {
    console.log(`  ${row.name.padEnd(24)} ${row.cpu.toFixed(1)}`);
  }
} finally {
  await session.end();
}
