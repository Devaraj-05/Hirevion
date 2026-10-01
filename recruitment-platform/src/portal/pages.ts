/** The candidate portal's pages (master plan §6.3); SP-07 fills them. */
export const PORTAL_PAGES = [
  { key: "status", path: "/" },
  { key: "invitation", path: "/invitation/[token]" },
  { key: "setPassword", path: "/set-password" },
  { key: "download", path: "/download" },
  { key: "notices", path: "/notices" },
  { key: "report", path: "/report" },
  { key: "requests", path: "/requests" },
] as const;

export type PortalPageKey = (typeof PORTAL_PAGES)[number]["key"];

export const PORTAL_OWNER = "SP-07";
