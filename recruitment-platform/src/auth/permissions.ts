import type { components } from "@hirevion/api-client";

/**
 * Who may open what. The roles are PRD §6's. The permission map is provisional: SP-02's
 * server-side RBAC matrix (with custom roles) replaces ROLE_PERMISSIONS and sends each session's
 * permissions from the API.
 */

export const ROLES = [
  "super_admin",
  "org_admin",
  "recruiter",
  "hiring_manager",
  "interviewer",
] as const;
export type Role = (typeof ROLES)[number];

export const PERMISSIONS = [
  "dashboard.view",
  "jobs.view",
  "jobs.create",
  "candidates.view",
  "candidates.manage",
  "interviews.view",
  "interviews.manage",
  "interviews.templates.view",
  "interviews.templates.manage",
  "questions.view",
  "questions.manage",
  "reports.view",
  "reports.interview.view",
  "reports.proctoring.view",
  "reports.candidate.view",
  "reports.analytics.view",
  "notifications.view",
  "account.manage",
  "admin.view",
  "admin.organization.manage",
  "admin.users.manage",
  "admin.roles.manage",
  "admin.teams.manage",
  "admin.departments.manage",
  "admin.ai.manage",
  "admin.integrations.manage",
  "admin.security.manage",
  "admin.proctoring.manage",
  "admin.retention.manage",
  "admin.branding.manage",
  "admin.webhooks.manage",
  "admin.api_keys.manage",
  "admin.usage.view",
  "admin.audit.view",
  "platform.view",
  "platform.organizations.manage",
  "platform.ai.manage",
  "platform.security.manage",
  "platform.app_catalog.manage",
  "platform.desktop_releases.manage",
  "platform.audit.view",
  "platform.health.view",
] as const;
export type Permission = (typeof PERMISSIONS)[number];

// The API's session type lists the server's catalogue (generated from its OpenAPI document);
// this fails to compile when the two lists differ.
type ApiPermission = components["schemas"]["SessionResponse"]["permissions"][number];
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
export const permissionsMatchTheApi: Same<Permission, ApiPermission> = true;

export interface Session {
  user: { id: string; name: string; email: string };
  /** null for the super admin, who works across organisations. */
  organization: { id: string; name: string } | null;
  /** System role keys: the five PRD §6 roles. */
  roles: readonly string[];
  /** The organisation's own roles the user holds, by name (ADR-0014). */
  customRoles: readonly string[];
  permissions: readonly Permission[];
  /** "api" for a real sign-in; "dev" for a development fixture, which has no account behind it. */
  source: "api" | "dev";
}

export function isRole(value: unknown): value is Role {
  return ROLES.some((role) => role === value);
}

export function isPermission(value: unknown): value is Permission {
  return PERMISSIONS.some((permission) => permission === value);
}

export function can(session: Session, permission: Permission): boolean {
  return session.permissions.includes(permission);
}

export const ROLE_PERMISSIONS: Record<Role, readonly Permission[]> = {
  super_admin: PERMISSIONS,
  org_admin: PERMISSIONS.filter((permission) => !permission.startsWith("platform.")),
  recruiter: [
    "dashboard.view",
    "jobs.view",
    "jobs.create",
    "candidates.view",
    "candidates.manage",
    "interviews.view",
    "interviews.manage",
    "interviews.templates.view",
    "interviews.templates.manage",
    "questions.view",
    "questions.manage",
    "reports.view",
    "reports.interview.view",
    "reports.proctoring.view",
    "reports.candidate.view",
    "reports.analytics.view",
    "notifications.view",
    "account.manage",
  ],
  hiring_manager: [
    "dashboard.view",
    "jobs.view",
    "candidates.view",
    "interviews.view",
    "reports.view",
    "reports.interview.view",
    "reports.proctoring.view",
    "reports.candidate.view",
    "notifications.view",
    "account.manage",
  ],
  interviewer: [
    "dashboard.view",
    "interviews.view",
    "reports.view",
    "reports.interview.view",
    "notifications.view",
    "account.manage",
  ],
};
