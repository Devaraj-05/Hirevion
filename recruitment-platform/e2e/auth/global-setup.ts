import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

/**
 * The sign-in suite signs in, steps up and asks for resets many times from one address, so a
 * second run within the hour would meet the first one's rate limits. Start from none.
 */
export default function globalSetup(): void {
  execFileSync(process.env.HV_UV ?? "uv", ["run", "hv", "reset-limits"], {
    cwd: fileURLToPath(new URL("../../../", import.meta.url)),
    stdio: "inherit",
  });
}
