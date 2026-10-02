import { describe, expect, it } from "vitest";
import { DEV_SESSIONS } from "./dev-sessions";
import { homeFor } from "./home";
import type { Permission, Session } from "./permissions";

function withPermissions(...permissions: Permission[]): Session {
  return { ...DEV_SESSIONS.recruiter, roles: [], customRoles: ["Custom"], permissions };
}

describe("homeFor", () => {
  it("is the dashboard for anyone who may see it", () => {
    expect(homeFor(DEV_SESSIONS.interviewer)).toBe("/dashboard");
  });

  it("is otherwise the first page the session may open", () => {
    expect(homeFor(withPermissions("account.manage", "admin.teams.manage", "jobs.view"))).toBe(
      "/jobs",
    );
  });

  it("is the account page when nothing else is open", () => {
    expect(homeFor(withPermissions("account.manage"))).toBe("/account");
  });
});
