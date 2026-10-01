import { describe, expect, it } from "vitest";
import { DEV_SESSIONS } from "@/auth/dev-sessions";
import enIN from "../../messages/en-IN.json";
import enUS from "../../messages/en-US.json";
import { tabsFor } from "./tabs";

const none = new URLSearchParams();

function keys(tabs: ReturnType<typeof tabsFor>): string[] | undefined {
  return tabs?.map((tab) => tab.key);
}

function active(tabs: ReturnType<typeof tabsFor>): string[] | undefined {
  return tabs?.filter((tab) => tab.active).map((tab) => tab.key);
}

describe("tabsFor", () => {
  it("gives a section's list pages their tabs, and other pages none", () => {
    expect(keys(tabsFor("/jobs", DEV_SESSIONS.recruiter, none))).toEqual([
      "all",
      "draft",
      "open",
      "paused",
      "closed",
      "archived",
    ]);
    expect(tabsFor("/jobs/new", DEV_SESSIONS.recruiter, none)).toBeUndefined();
    expect(tabsFor("/dashboard", DEV_SESSIONS.recruiter, none)).toBeUndefined();
  });

  it("marks the tab matching the current filter", () => {
    expect(
      active(tabsFor("/jobs", DEV_SESSIONS.recruiter, new URLSearchParams("status=paused"))),
    ).toEqual(["paused"]);
    expect(active(tabsFor("/jobs", DEV_SESSIONS.recruiter, none))).toEqual(["all"]);
    expect(active(tabsFor("/interviews/templates", DEV_SESSIONS.recruiter, none))).toEqual([
      "templates",
    ]);
  });

  it("links filter tabs through the URL", () => {
    const tabs = tabsFor("/candidates", DEV_SESSIONS.recruiter, none);
    expect(tabs?.find((tab) => tab.key === "shortlisted")?.href).toBe(
      "/candidates?stage=shortlisted",
    );
    expect(tabs?.find((tab) => tab.key === "all")?.href).toBe("/candidates");
  });

  it("has a label for every tab in both languages", () => {
    for (const path of ["/jobs", "/candidates", "/interviews", "/questions", "/reports"] as const) {
      for (const tab of tabsFor(path, DEV_SESSIONS.super_admin, none) ?? []) {
        for (const catalogue of [enIN, enUS]) {
          const section = catalogue.tabs[tab.section] as Record<string, string>;
          expect(section[tab.key], `${tab.section}.${tab.key}`).toBeTruthy();
        }
      }
    }
  });

  it("leaves out tabs the session can't open", () => {
    expect(keys(tabsFor("/reports", DEV_SESSIONS.interviewer, none))).toEqual(["interview"]);
    expect(keys(tabsFor("/interviews", DEV_SESSIONS.interviewer, none))).not.toContain("templates");
  });
});
