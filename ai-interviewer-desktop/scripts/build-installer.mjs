// Builds the Windows installer(s): `pnpm --filter @hirevion/ai-interviewer-desktop bundle`.
//
//   --target x64|arm64|all   default x64 (arm64 needs the VS "ARM64 build tools" component)
//   --no-updater             skip the signed update artifacts (no updater key needed)
//
// Environment (also read from the root .env; real environment wins):
//   HV_API_URL                         API root compiled into the app (https, ends in /api/v1)
//   HV_GLITCHTIP_DSN                   crash reporting; absent = off
//   TAURI_SIGNING_PRIVATE_KEY          updater key (path or text); defaults to the dev key at
//                                      %USERPROFILE%\.hirevion\updater-dev.key
//   TAURI_SIGNING_PRIVATE_KEY_PASSWORD its password
//   HV_SIGN=0                          skip Authenticode signing (default: sign)
//   HV_SIGN_THUMBPRINT                 certificate to sign with; default is the self-signed dev
//                                      certificate, created on demand in CurrentUser\My
//   HV_SIGN_TIMESTAMP_URL              RFC 3161 timestamp server (production certificates)
//
// Authenticode signing happens inside the Tauri bundler, before the updater signature is made,
// so the minisign signature covers the exact file that ships.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadDotEnv } from "./dotenv.mjs";
import { authenticodeStatus } from "./powershell.mjs";

const appRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const tauriDir = join(appRoot, "src-tauri");
const TRIPLES = { x64: "x86_64-pc-windows-msvc", arm64: "aarch64-pc-windows-msvc" };

function fail(message) {
  console.error(`\nbuild-installer: ${message}`);
  process.exit(1);
}

function parseArgs(argv) {
  const options = { target: "x64", updater: true };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--") continue; // pnpm passes the separator through
    if (argv[i] === "--target") options.target = argv[++i];
    else if (argv[i] === "--no-updater") options.updater = false;
    else fail(`unknown option ${argv[i]}`);
  }
  if (options.target !== "all" && !TRIPLES[options.target]) fail("--target is x64, arm64 or all");
  return options;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", cwd: appRoot, ...options });
  if (result.status !== 0) fail(`${command} ${args.slice(0, 2).join(" ")} failed`);
}

function devCertificateThumbprint() {
  const result = spawnSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      join(appRoot, "scripts", "dev-signing-cert.ps1"),
    ],
    { encoding: "utf8" },
  );
  const thumbprint = (result.stdout ?? "").trim().split(/\r?\n/).pop();
  if (result.status !== 0 || !/^[0-9A-Fa-f]{40}$/.test(thumbprint ?? "")) {
    fail(`couldn't get a signing certificate: ${result.stderr || result.stdout}`);
  }
  return thumbprint;
}

function describeInstaller(file) {
  const bytes = readFileSync(file);
  const mib = (statSync(file).size / 1024 / 1024).toFixed(1);
  console.log(`\n  ${file}`);
  console.log(`    size    ${mib} MiB`);
  console.log(`    sha256  ${createHash("sha256").update(bytes).digest("hex")}`);
  console.log(`    signed  ${authenticodeStatus(file)}`);
  const signature = `${file}.sig`;
  if (existsSync(signature)) {
    const text = Buffer.from(readFileSync(signature, "utf8").trim(), "base64").toString("utf8");
    const trusted = text.split(/\r?\n/).find((line) => line.startsWith("trusted comment:"));
    console.log(`    updater ${signature}`);
    console.log(`            ${trusted ?? "(no trusted comment)"}`);
  }
}

const options = parseArgs(process.argv.slice(2));
const loaded = loadDotEnv(appRoot);
if (loaded.length) console.log(`Read ${loaded.join(", ")}`);

const override = { bundle: { windows: {} } };

if (options.updater) {
  const defaultKey = join(homedir(), ".hirevion", "updater-dev.key");
  if (!process.env.TAURI_SIGNING_PRIVATE_KEY && existsSync(defaultKey)) {
    process.env.TAURI_SIGNING_PRIVATE_KEY = defaultKey;
  }
  if (!process.env.TAURI_SIGNING_PRIVATE_KEY) {
    fail(
      "no updater key. Make the development key (docs/runbooks/local-dev.md, 'Updates'), or pass --no-updater.",
    );
  }
  if (process.env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD === undefined) {
    fail("TAURI_SIGNING_PRIVATE_KEY_PASSWORD isn't set (it belongs in the root .env).");
  }
} else {
  override.bundle.createUpdaterArtifacts = false;
}

if (process.env.HV_SIGN === "0") {
  console.log("HV_SIGN=0: not signing with Authenticode.");
} else {
  const thumbprint = process.env.HV_SIGN_THUMBPRINT || devCertificateThumbprint();
  console.log(`Signing with certificate ${thumbprint}`);
  override.bundle.windows.certificateThumbprint = thumbprint;
  override.bundle.windows.digestAlgorithm = "sha256";
  if (process.env.HV_SIGN_TIMESTAMP_URL) {
    override.bundle.windows.timestampUrl = process.env.HV_SIGN_TIMESTAMP_URL;
  }
}

mkdirSync(join(tmpdir(), "hirevion-build"), { recursive: true });
const overrideFile = join(tmpdir(), "hirevion-build", `tauri-override-${process.pid}.json`);
writeFileSync(overrideFile, JSON.stringify(override));

const tauriCli = createRequire(import.meta.url).resolve("@tauri-apps/cli/tauri.js");
const targets = options.target === "all" ? ["x64", "arm64"] : [options.target];
const built = [];
for (const name of targets) {
  const triple = TRIPLES[name];
  console.log(`\n== ${name} (${triple}) ==`);
  run("rustup", ["target", "add", triple]);
  run(process.execPath, [
    tauriCli,
    "build",
    "--target",
    triple,
    "--bundles",
    "nsis",
    "--config",
    overrideFile,
  ]);
  const folder = join(tauriDir, "target", triple, "release", "bundle", "nsis");
  const installers = existsSync(folder)
    ? readdirSync(folder).filter((file) => file.endsWith("-setup.exe"))
    : [];
  if (installers.length === 0) fail(`no installer in ${folder}`);
  built.push(...installers.map((file) => join(folder, file)));
}

console.log("\nBuilt:");
for (const file of built) describeInstaller(file);
