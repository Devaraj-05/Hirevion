/** The candidate portal's pages (master plan §6.3; SP-07b). */
export const PORTAL_PAGES = [
  { key: "status", path: "/" },
  { key: "login", path: "/login" },
  { key: "forgotPassword", path: "/forgot-password" },
  { key: "resetPassword", path: "/reset-password/[token]" },
  { key: "invitation", path: "/invitation/[token]" },
  { key: "download", path: "/download" },
  { key: "notices", path: "/notices" },
  { key: "report", path: "/report" },
  { key: "requests", path: "/requests" },
] as const;

export type PortalPageKey = (typeof PORTAL_PAGES)[number]["key"];
