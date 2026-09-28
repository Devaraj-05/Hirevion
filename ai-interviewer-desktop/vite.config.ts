import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Tauri loads the dev server at http://localhost:1420 (tauri.conf.json `devUrl`).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    sourcemap: Boolean(process.env.TAURI_ENV_DEBUG),
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
