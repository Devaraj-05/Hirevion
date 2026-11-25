import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Tauri loads the dev server at http://localhost:1420 (tauri.conf.json `devUrl`).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  // The dev server pre-bundles dependencies it finds by crawling the app's imports, but not
  // those of web workers: it found MediaPipe only when the face module's worker started
  // mid-interview, re-bundled and reloaded the page (the white screen of 2026-11-25). Listing
  // the workers' and the recorder's dependencies here bundles them at start-up instead.
  optimizeDeps: {
    include: ["@mediapipe/tasks-vision", "mediabunny", "livekit-client"],
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    sourcemap: Boolean(process.env.TAURI_ENV_DEBUG),
  },
  test: {
    include: ["src/**/*.test.ts", "e2e/**/*.test.mjs", "scripts/**/*.test.mjs"],
  },
});
