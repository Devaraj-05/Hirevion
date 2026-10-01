import { describe, expect, it } from "vitest";
import { DEV_SESSIONS } from "@/auth/dev-sessions";
import { routeAt } from "@/auth/manifest";
import { breadcrumbTrail, isActive, navRoutes, SHORTCUTS } from "./nav";

describe("navRoutes", () => {
  it("lists the sidebar sections the session may open, in manifest order", () => {
    expect(navRoutes(DEV_SESSIONS.interviewer).map((route) => route.path)).toEqual([
      "/dashboard",
      "/interviews",
      "/reports",
    ]);
  });
});

describe("isActive", () => {
  it("covers a section's own pages, not its look-alikes", () => {
    expect(isActive("/jobs", "/jobs")).toBe(true);
    expect(isActive("/jobs/new", "/jobs")).toBe(true);
    expect(isActive("/jobsx", "/jobs")).toBe(false);
  });
});

describe("breadcrumbTrail", () => {
  it("leads from the section to the page", () => {
    expect(breadcrumbTrail("/admin/users")).toEqual([routeAt("/admin"), routeAt("/admin/users")]);
    expect(breadcrumbTrail("/jobs/0192-some-job")).toEqual([routeAt("/jobs")]);
  });

  it("is just the page for a section's own page, and empty off the manifest", () => {
    expect(breadcrumbTrail("/dashboard")).toEqual([routeAt("/dashboard")]);
    expect(breadcrumbTrail("/notifications")).toEqual([routeAt("/notifications")]);
    expect(breadcrumbTrail("/login")).toEqual([]);
  });
});

describe("SHORTCUTS", () => {
  it("go to sidebar sections", () => {
    for (const path of Object.values(SHORTCUTS)) {
      expect(routeAt(path).nav, path).toBe(true);
    }
    expect(SHORTCUTS).toMatchObject({
      d: "/dashboard",
      j: "/jobs",
      c: "/candidates",
      i: "/interviews",
    });
  });
});
