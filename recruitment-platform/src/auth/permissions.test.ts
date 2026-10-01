import { describe, expect, it } from "vitest";
import { DEV_SESSIONS } from "./dev-sessions";
import { ROUTES, routeFor } from "./manifest";
import { can, type Permission, type Role } from "./permissions";

function opens(role: Role, path: string): boolean {
  const route = routeFor(path);
  if (!route) throw new Error(`no manifest entry for ${path}`);
  return can(DEV_SESSIONS[role], route.permission);
}

describe("the provisional role matrix (PRD §6; SP-02 makes it authoritative)", () => {
  it("lets only the super admin reach the platform pages", () => {
    expect(opens("super_admin", "/platform/organizations")).toBe(true);
    for (const role of ["org_admin", "recruiter", "hiring_manager", "interviewer"] as const) {
      expect(opens(role, "/platform/organizations")).toBe(false);
    }
  });

  it("lets organisation admins administer their organisation", () => {
    expect(opens("org_admin", "/admin/users")).toBe(true);
    expect(opens("org_admin", "/admin/audit-logs")).toBe(true);
    expect(opens("recruiter", "/admin/users")).toBe(false);
  });

  it("gives recruiters the hiring work but not administration", () => {
    for (const path of [
      "/jobs",
      "/jobs/new",
      "/candidates",
      "/interviews",
      "/questions",
      "/reports",
    ]) {
      expect(opens("recruiter", path)).toBe(true);
    }
    expect(opens("recruiter", "/reports/analytics")).toBe(true);
    expect(opens("recruiter", "/admin")).toBe(false);
  });

  it("lets hiring managers view, not create", () => {
    for (const path of [
      "/dashboard",
      "/jobs",
      "/candidates",
      "/interviews",
      "/reports/candidate",
    ]) {
      expect(opens("hiring_manager", path)).toBe(true);
    }
    expect(opens("hiring_manager", "/jobs/new")).toBe(false);
    expect(opens("hiring_manager", "/questions")).toBe(false);
  });

  it("gives interviewers their interviews and interview reports only", () => {
    expect(opens("interviewer", "/dashboard")).toBe(true);
    expect(opens("interviewer", "/interviews")).toBe(true);
    expect(opens("interviewer", "/reports/interview")).toBe(true);
    for (const path of ["/jobs", "/candidates", "/reports/analytics", "/questions"]) {
      expect(opens("interviewer", path)).toBe(false);
    }
  });

  it("refuses everything to a session without the permission", () => {
    const none = { ...DEV_SESSIONS.recruiter, permissions: [] as Permission[] };
    expect(can(none, "jobs.view")).toBe(false);
  });
});

describe("routeFor", () => {
  it("matches the longest prefix, so detail pages inherit their section", () => {
    expect(routeFor("/jobs/new")?.permission).toBe("jobs.create");
    expect(routeFor("/jobs/0192-some-job")?.path).toBe("/jobs");
    expect(routeFor("/interviews/templates")?.permission).toBe("interviews.templates.view");
  });

  it("knows nothing of public or unknown paths", () => {
    expect(routeFor("/login")).toBeUndefined();
    expect(routeFor("/forbidden")).toBeUndefined();
    expect(routeFor("/jobsx")).toBeUndefined();
  });

  it("covers every PRD §7 section in the navigation", () => {
    const sections = ROUTES.filter((route) => route.nav).map((route) => route.section);
    expect(sections).toEqual([
      "dashboard",
      "jobs",
      "candidates",
      "interviews",
      "questions",
      "reports",
      "admin",
      "platform",
    ]);
  });
});
