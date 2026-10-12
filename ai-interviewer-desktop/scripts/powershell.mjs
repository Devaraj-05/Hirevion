// Runs PowerShell with values passed as environment variables (`$env:HV_ARG_<NAME>`), never
// spliced into the script text. A path with an apostrophe, `$`, backtick or `;` (a profile
// folder like O'Brien's) then can't break the command or change what it does.
import { spawnSync } from "node:child_process";

/** Runs `script`; each `args` entry NAME is readable as `$env:HV_ARG_NAME`. */
export function powershell(script, args = {}) {
  const env = { ...process.env };
  for (const [name, value] of Object.entries(args)) env[`HV_ARG_${name}`] = String(value);
  return spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    encoding: "utf8",
    env,
  });
}

/** "Valid", "NotSigned", "UnknownError" (a certificate Windows doesn't trust), plus who signed. */
export function authenticodeStatus(file) {
  const result = powershell(
    '$s = Get-AuthenticodeSignature -LiteralPath $env:HV_ARG_FILE; "$($s.Status) $($s.SignerCertificate.Subject) $($s.SignerCertificate.Thumbprint)"',
    { FILE: file },
  );
  return (result.stdout ?? "").trim();
}

/** Unpacks a .zip into `folder`, which must be a path PowerShell may create. */
export function expandArchive(zip, folder) {
  const result = powershell(
    "Expand-Archive -LiteralPath $env:HV_ARG_ZIP -DestinationPath $env:HV_ARG_DIR -Force",
    { ZIP: zip, DIR: folder },
  );
  if (result.status !== 0) {
    throw new Error(`couldn't unpack ${zip} into ${folder}: ${result.stderr || result.stdout}`);
  }
}
