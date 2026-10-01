import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { assertSafeEnvironment } from "./src/config/environment";

assertSafeEnvironment();

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  // `next dev` only: Caddy serves the app on these hosts, and Next blocks its dev assets
  // (hot reload, chunks) for origins it doesn't know.
  allowedDevOrigins: ["app.hirevion.localhost", "candidate.hirevion.localhost"],
  poweredByHeader: false,
  reactStrictMode: true,
  // proxy.ts rewrites each host onto its own route tree. Without this, the proxy sees its URL on a
  // fallback host ("localhost") that differs from the server's own, so Next sends every rewrite
  // back over the network to itself, where it is rewritten again, endlessly.
  skipProxyUrlNormalize: true,
  transpilePackages: ["@hirevion/ui", "@hirevion/api-client"],
};

export default withNextIntl(nextConfig);
