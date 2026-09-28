import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Phones reach this dev server through a Cloudflare quick tunnel and Caddy's tunnel site
// (http://127.0.0.1:8088, `uv run hv eye-tunnel`); this PC can use https://eye.hirevion.localhost.
// Both arrive on HTTPS port 443, which is where the hot-reload socket must connect back to.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    // IPv4 loopback: Docker Desktop forwards host.docker.internal (Caddy's upstream) there,
    // and Node's "localhost" may listen on IPv6 only.
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    allowedHosts: [".trycloudflare.com", "eye.hirevion.localhost"],
    hmr: { clientPort: 443 },
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
