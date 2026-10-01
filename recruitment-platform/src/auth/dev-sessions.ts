import { ROLE_PERMISSIONS, type Role, type Session } from "./permissions";

/**
 * One synthetic session per role, for development and the end-to-end tests until SP-02 brings
 * real sign-in. Only reachable when HV_WEB_DEV_TOOLS=true, which production refuses.
 */

const ORGANIZATION = { id: "01920000-0000-7000-8000-000000000001", name: "Acme Talent (dev)" };

function fixture(role: Role, id: string, name: string, email: string): Session {
  return {
    user: { id, name, email },
    organization: role === "super_admin" ? null : ORGANIZATION,
    roles: [role],
    permissions: ROLE_PERMISSIONS[role],
    source: "dev",
  };
}

export const DEV_SESSIONS: Record<Role, Session> = {
  super_admin: fixture(
    "super_admin",
    "01920000-0000-7000-8000-000000000011",
    "Sam Platform",
    "sam@example.test",
  ),
  org_admin: fixture(
    "org_admin",
    "01920000-0000-7000-8000-000000000012",
    "Olivia Admin",
    "olivia@example.test",
  ),
  recruiter: fixture(
    "recruiter",
    "01920000-0000-7000-8000-000000000013",
    "Ravi Recruiter",
    "ravi@example.test",
  ),
  hiring_manager: fixture(
    "hiring_manager",
    "01920000-0000-7000-8000-000000000014",
    "Hema Manager",
    "hema@example.test",
  ),
  interviewer: fixture(
    "interviewer",
    "01920000-0000-7000-8000-000000000015",
    "Ishan Reviewer",
    "ishan@example.test",
  ),
};
