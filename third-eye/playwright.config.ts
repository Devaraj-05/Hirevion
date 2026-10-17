import { defineConfig, devices } from "@playwright/test";

const PORT = 5175;

/**
 * The phone-emulation path (ADR-0008, ADR-0040): headless Chromium with a fake 720p camera opens
 * the built page as a phone would. The API is answered in the test; the streaming spec joins
 * the local LiveKit (`uv run hv up`) and is skipped without its keys.
 */
export default defineConfig({
  testDir: "./e2e",
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"]],
  timeout: 90_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    permissions: ["camera"],
    launchOptions: {
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
    },
  },
  projects: [{ name: "phone", use: { ...devices["Pixel 7"] } }],
  webServer: {
    command: `vite build && vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
