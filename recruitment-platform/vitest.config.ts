import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    // `pnpm test:coverage` (the web coverage gate): V8 coverage of the app's own source.
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "**/*.d.ts"],
      reporter: ["text-summary", "json-summary"],
      reportsDirectory: "coverage",
      // What was measured on 2026-10-22, rounded down: the gate only lets coverage rise. Raise
      // these when it does.
      thresholds: { lines: 72, statements: 71, branches: 66, functions: 66 },
    },
    // Logic runs on Node; components (.tsx tests) run in jsdom.
    projects: [
      { extends: true, test: { name: "node", include: ["src/**/*.test.ts"], environment: "node" } },
      {
        extends: true,
        test: {
          name: "dom",
          include: ["src/**/*.test.tsx"],
          environment: "jsdom",
          setupFiles: ["./vitest.setup.ts"],
          // Above Testing Library's 5 s async wait (vitest.setup.ts), so a slow render fails on
          // what it waited for, not on the test's own clock.
          testTimeout: 20_000,
        },
      },
    ],
  },
});
