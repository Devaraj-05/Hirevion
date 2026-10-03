import type catalogue from "../../messages/en-IN.json";
import type { Permission } from "./permissions";

/**
 * Every guarded page on the recruiter host (PRD §7, master plan §6.2): the permission it needs,
 * its title in the `routes` message namespace, and the sub-project that fills it. The navigation,
 * the command palette, the proxy guard and each page's own check all read this list; a test keeps
 * it in step with the pages on disk.
 */

export type Section =
  | "dashboard"
  | "jobs"
  | "candidates"
  | "interviews"
  | "questions"
  | "reports"
  | "notifications"
  | "account"
  | "admin"
  | "platform";

export type RouteTitleKey = keyof (typeof catalogue)["routes"];

export interface RouteEntry {
  path: string;
  permission: Permission;
  section: Section;
  titleKey: RouteTitleKey;
  owner: string;
  /** Shown in the sidebar, in this list's order. */
  nav?: true;
  /** A page about one record ("/jobs/[id]"): guarded, but reached from its list, never listed. */
  detail?: true;
}

// Keeps each entry's literal path (for RoutePath) while checking it against RouteEntry.
function route<const Entry extends RouteEntry>(entry: Entry): Entry & RouteEntry {
  return entry;
}

export const ROUTES = [
  route({
    path: "/dashboard",
    permission: "dashboard.view",
    section: "dashboard",
    titleKey: "dashboard",
    owner: "SP-21",
    nav: true,
  }),
  route({
    path: "/jobs",
    permission: "jobs.view",
    section: "jobs",
    titleKey: "jobs",
    owner: "SP-04",
    nav: true,
  }),
  route({
    path: "/jobs/new",
    permission: "jobs.create",
    section: "jobs",
    titleKey: "jobsNew",
    owner: "SP-04",
  }),
  route({
    path: "/jobs/[id]",
    permission: "jobs.view",
    section: "jobs",
    titleKey: "jobsDetail",
    owner: "SP-04",
    detail: true,
  }),
  route({
    path: "/candidates",
    permission: "candidates.view",
    section: "candidates",
    titleKey: "candidates",
    owner: "SP-05",
    nav: true,
  }),
  route({
    path: "/candidates/[id]",
    permission: "candidates.view",
    section: "candidates",
    titleKey: "candidatesDetail",
    owner: "SP-04",
    detail: true,
  }),
  route({
    path: "/interviews",
    permission: "interviews.view",
    section: "interviews",
    titleKey: "interviews",
    owner: "SP-07",
    nav: true,
  }),
  route({
    path: "/interviews/templates",
    permission: "interviews.templates.view",
    section: "interviews",
    titleKey: "interviewTemplates",
    owner: "SP-06",
  }),
  route({
    path: "/questions",
    permission: "questions.view",
    section: "questions",
    titleKey: "questions",
    owner: "SP-06",
    nav: true,
  }),
  route({
    path: "/reports",
    permission: "reports.view",
    section: "reports",
    titleKey: "reports",
    owner: "SP-17",
    nav: true,
  }),
  route({
    path: "/reports/interview",
    permission: "reports.interview.view",
    section: "reports",
    titleKey: "reportsInterview",
    owner: "SP-17",
  }),
  route({
    path: "/reports/proctoring",
    permission: "reports.proctoring.view",
    section: "reports",
    titleKey: "reportsProctoring",
    owner: "SP-17",
  }),
  route({
    path: "/reports/candidate",
    permission: "reports.candidate.view",
    section: "reports",
    titleKey: "reportsCandidate",
    owner: "SP-17",
  }),
  route({
    path: "/reports/analytics",
    permission: "reports.analytics.view",
    section: "reports",
    titleKey: "reportsAnalytics",
    owner: "SP-21",
  }),
  route({
    path: "/notifications",
    permission: "notifications.view",
    section: "notifications",
    titleKey: "notifications",
    owner: "SP-18",
  }),
  route({
    path: "/account",
    permission: "account.manage",
    section: "account",
    titleKey: "account",
    owner: "SP-02a",
  }),
  route({
    path: "/admin",
    permission: "admin.view",
    section: "admin",
    titleKey: "admin",
    owner: "SP-22",
    nav: true,
  }),
  route({
    path: "/admin/organization",
    permission: "admin.organization.manage",
    section: "admin",
    titleKey: "adminOrganization",
    owner: "SP-02",
  }),
  route({
    path: "/admin/users",
    permission: "admin.users.manage",
    section: "admin",
    titleKey: "adminUsers",
    owner: "SP-02",
  }),
  route({
    path: "/admin/roles",
    permission: "admin.roles.manage",
    section: "admin",
    titleKey: "adminRoles",
    owner: "SP-02",
  }),
  route({
    path: "/admin/teams",
    permission: "admin.teams.manage",
    section: "admin",
    titleKey: "adminTeams",
    owner: "SP-02",
  }),
  route({
    path: "/admin/departments",
    permission: "admin.departments.manage",
    section: "admin",
    titleKey: "adminDepartments",
    owner: "SP-02",
  }),
  route({
    path: "/admin/ai",
    permission: "admin.ai.manage",
    section: "admin",
    titleKey: "adminAi",
    owner: "SP-22",
  }),
  route({
    path: "/admin/integrations",
    permission: "admin.integrations.manage",
    section: "admin",
    titleKey: "adminIntegrations",
    owner: "SP-20",
  }),
  route({
    path: "/admin/security",
    permission: "admin.security.manage",
    section: "admin",
    titleKey: "adminSecurity",
    owner: "SP-19",
  }),
  route({
    path: "/admin/proctoring",
    permission: "admin.proctoring.manage",
    section: "admin",
    titleKey: "adminProctoring",
    owner: "SP-22",
  }),
  route({
    path: "/admin/retention",
    permission: "admin.retention.manage",
    section: "admin",
    titleKey: "adminRetention",
    owner: "SP-22",
  }),
  route({
    path: "/admin/branding",
    permission: "admin.branding.manage",
    section: "admin",
    titleKey: "adminBranding",
    owner: "SP-22",
  }),
  route({
    path: "/admin/webhooks",
    permission: "admin.webhooks.manage",
    section: "admin",
    titleKey: "adminWebhooks",
    owner: "SP-18",
  }),
  route({
    path: "/admin/api-keys",
    permission: "admin.api_keys.manage",
    section: "admin",
    titleKey: "adminApiKeys",
    owner: "SP-20",
  }),
  route({
    path: "/admin/usage",
    permission: "admin.usage.view",
    section: "admin",
    titleKey: "adminUsage",
    owner: "SP-22",
  }),
  route({
    path: "/admin/audit-logs",
    permission: "admin.audit.view",
    section: "admin",
    titleKey: "adminAuditLogs",
    owner: "SP-22",
  }),
  route({
    path: "/platform",
    permission: "platform.view",
    section: "platform",
    titleKey: "platform",
    owner: "SP-22",
    nav: true,
  }),
  route({
    path: "/platform/organizations",
    permission: "platform.organizations.manage",
    section: "platform",
    titleKey: "platformOrganizations",
    owner: "SP-02",
  }),
  route({
    path: "/platform/ai",
    permission: "platform.ai.manage",
    section: "platform",
    titleKey: "platformAi",
    owner: "SP-22",
  }),
  route({
    path: "/platform/security",
    permission: "platform.security.manage",
    section: "platform",
    titleKey: "platformSecurity",
    owner: "SP-22",
  }),
  route({
    path: "/platform/app-catalog",
    permission: "platform.app_catalog.manage",
    section: "platform",
    titleKey: "platformAppCatalog",
    owner: "SP-22",
  }),
  route({
    path: "/platform/desktop-releases",
    permission: "platform.desktop_releases.manage",
    section: "platform",
    titleKey: "platformDesktopReleases",
    owner: "SP-07",
  }),
  route({
    path: "/platform/audit",
    permission: "platform.audit.view",
    section: "platform",
    titleKey: "platformAudit",
    owner: "SP-22",
  }),
  route({
    path: "/platform/health",
    permission: "platform.health.view",
    section: "platform",
    titleKey: "platformHealth",
    owner: "SP-22",
  }),
];

export type ManifestRoute = (typeof ROUTES)[number];
export type RoutePath = ManifestRoute["path"];

/** The entry that guards a path: its own, or its closest listed ancestor's (detail pages). */
export function routeFor(pathname: string): ManifestRoute | undefined {
  let match: ManifestRoute | undefined;
  for (const entry of ROUTES) {
    const covers = pathname === entry.path || pathname.startsWith(`${entry.path}/`);
    if (covers && (!match || entry.path.length > match.path.length)) match = entry;
  }
  return match;
}

export function routeAt(path: RoutePath): ManifestRoute {
  const entry = ROUTES.find((candidate) => candidate.path === path);
  if (!entry) throw new Error(`no route ${path}`);
  return entry;
}
