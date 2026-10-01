import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;
const CI = Boolean(process.env.CI);
// HV_E2E_API=1: the sign-in suite (e2e/auth) against the real API, which must already run
// (`uv run hv api`, with Mailpit and a seeded database). Otherwise: the web suite, with
// development sessions and no API. Each mode is its own run and build.
const WITH_API = process.env.HV_E2E_API === "1";
const API = process.env.HV_API_INTERNAL_URL ?? "http://127.0.0.1:8000";

/**
 * A production build serves the app. In the web mode it runs on 3100 with the development
 * sessions on. In the API mode it runs on 3101 without them, behind a small gateway on 3100
 * that sends /api/* to the API, as Caddy does, so the session cookie is same-origin.
 */
const webServer = WITH_API
  ? [
      {
        // `next` directly, not through `pnpm exec`: pnpm doesn't pass the stop signal on.
        command: `next build && next start -H 127.0.0.1 -p ${PORT + 1}`,
        url: `http://127.0.0.1:${PORT + 1}/login`,
        env: { HV_WEB_DEV_TOOLS: "false", HV_API_INTERNAL_URL: API },
        reuseExistingServer: !CI,
        timeout: 240_000,
      },
      {
        command: "node e2e/auth/gateway.mjs",
        url: `http://127.0.0.1:${PORT}/login`,
        env: {
          HV_API_INTERNAL_URL: API,
          HV_GATEWAY_PORT: String(PORT),
          HV_WEB_PORT: String(PORT + 1),
        },
        reuseExistingServer: !CI,
        timeout: 30_000,
      },
    ]
  : {
      // `next` directly, not through `pnpm exec`: pnpm doesn't pass the stop signal on, so on
      // Linux the orphaned server kept its pipes open and Playwright waited for it forever.
      // `pnpm e2e` puts node_modules/.bin on PATH.
      command: `next build && next start -H 127.0.0.1 -p ${PORT}`,
      url: `http://127.0.0.1:${PORT}/login`,
      env: { HV_WEB_DEV_TOOLS: "true" },
      reuseExistingServer: !CI,
      timeout: 240_000,
    };

export default defineConfig({
  testDir: "./e2e",
  ...(WITH_API ? { testMatch: "auth/**/*.spec.ts" } : { testIgnore: "auth/**" }),
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
  projects: [{ name: WITH_API ? "auth" : "web", use: { ...devices["Desktop Chrome"] } }],
  webServer,
});
