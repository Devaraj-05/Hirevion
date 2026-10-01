import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;
const CI = Boolean(process.env.CI);

/**
 * End-to-end checks against a production build with the development sign-in on (the only
 * build the dev tools may run in outside `next dev`). Both hosts resolve to this one server.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  // In CI, stop (and still write the report) well before the job's own time limit.
  ...(CI ? { workers: 2, globalTimeout: 20 * 60_000 } : {}),
  reporter: CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  timeout: 60_000,
  use: {
    baseURL: `http://app.hirevion.localhost:${PORT}`,
    trace: "retain-on-failure",
    launchOptions: {
      // Chromium already sends *.localhost to loopback; pinning IPv4 matches the server's bind.
      args: ["--host-resolver-rules=MAP *.hirevion.localhost 127.0.0.1"],
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // `next` directly, not through `pnpm exec`: pnpm doesn't pass the stop signal on, so on
    // Linux the orphaned server kept its pipes open and Playwright waited for it forever.
    // `pnpm e2e` puts node_modules/.bin on PATH.
    command: `next build && next start -H 127.0.0.1 -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}/login`,
    env: { HV_WEB_DEV_TOOLS: "true" },
    reuseExistingServer: !CI,
    timeout: 240_000,
  },
});
