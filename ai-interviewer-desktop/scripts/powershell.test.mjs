// Paths reach PowerShell as environment variables, never spliced into a script, so an apostrophe
// (O'Brien's profile folder) or a `$` or backtick in a path can't break or change the command.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { authenticodeStatus, expandArchive, powershell } from "./powershell.mjs";

const windows = process.platform === "win32";
const root = mkdtempSync(join(tmpdir(), "hv-ps-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));

const AWKWARD = ["it's a folder", "dollar $env and `tick", "semi; colon (paren) & amp"];

describe.skipIf(!windows)("powershell", () => {
  it("passes a value with quotes and metacharacters through untouched", () => {
    for (const name of AWKWARD) {
      const folder = join(root, name);
      mkdirSync(folder, { recursive: true });
      const file = join(folder, "O'Brien's file.txt");
      writeFileSync(file, "12345");
      const result = powershell("(Get-Item -LiteralPath $env:HV_ARG_FILE).Length", { FILE: file });
      expect(result.status, result.stderr).toBe(0);
      expect(result.stdout.trim()).toBe("5");
    }
  });

  it("reads the signature of a file whose path has an apostrophe", () => {
    const file = join(root, "it's unsigned.ps1");
    writeFileSync(file, "Write-Output 1");
    expect(authenticodeStatus(file)).toMatch(/^NotSigned/);
  });

  it("unpacks an archive into a folder whose path has an apostrophe", () => {
    const source = join(root, "o'source");
    mkdirSync(source);
    writeFileSync(join(source, "msedgedriver.exe"), "x");
    const zip = join(root, "it's a driver.zip");
    const made = powershell(
      "Compress-Archive -LiteralPath (Join-Path $env:HV_ARG_SOURCE 'msedgedriver.exe') -DestinationPath $env:HV_ARG_ZIP",
      { SOURCE: source, ZIP: zip },
    );
    expect(made.status, made.stderr).toBe(0);
    const target = join(root, "o'brien's drivers");
    expandArchive(zip, target);
    const listed = powershell(
      "Test-Path -LiteralPath (Join-Path $env:HV_ARG_DIR 'msedgedriver.exe')",
      {
        DIR: target,
      },
    );
    expect(listed.stdout.trim()).toBe("True");
  });
});
