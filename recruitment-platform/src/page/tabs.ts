import { type RoutePath, routeAt } from "@/auth/manifest";
import { can, type Session } from "@/auth/permissions";

/**
 * The tabs of the list sections (PRD §7). A filter tab sets a URL parameter on its section's
 * list; a page tab (templates, the report types) is a route of its own.
 */

export type TabbedSection = "jobs" | "candidates" | "interviews" | "questions" | "reports";

interface TabDef {
  key: string;
  path: RoutePath;
  /** For a filter tab: the parameter and its value, or null for the unfiltered tab. */
  param?: { name: string; value: string | null };
}

interface TabSet {
  section: TabbedSection;
  /** The pages that show these tabs. */
  pages: readonly RoutePath[];
  tabs: readonly TabDef[];
}

function filterTabs(
  path: RoutePath,
  name: string,
  values: readonly [string, string | null][],
): TabDef[] {
  return values.map(([key, value]) => ({ key, path, param: { name, value } }));
}

const TAB_SETS: readonly TabSet[] = [
  {
    section: "jobs",
    pages: ["/jobs"],
    tabs: filterTabs("/jobs", "status", [
      ["all", null],
      ["draft", "draft"],
      ["open", "open"],
      ["paused", "paused"],
      ["closed", "closed"],
      ["archived", "archived"],
    ]),
  },
  {
    section: "candidates",
    pages: ["/candidates"],
    tabs: filterTabs("/candidates", "stage", [
      ["all", null],
      ["screening", "screening"],
      ["shortlisted", "shortlisted"],
      ["interview", "interview"],
      ["completed", "completed"],
      ["decision", "decision"],
    ]),
  },
  {
    section: "interviews",
    pages: ["/interviews", "/interviews/templates"],
    tabs: [
      ...filterTabs("/interviews", "status", [
        ["upcoming", null],
        ["live", "live"],
        ["completed", "completed"],
      ]),
      { key: "templates", path: "/interviews/templates" },
    ],
  },
  {
    section: "questions",
    pages: ["/questions"],
    tabs: filterTabs("/questions", "category", [
      ["all", null],
      ["technical", "technical"],
      ["coding", "coding"],
      ["system_design", "system_design"],
      ["resume_based", "resume_based"],
      ["custom", "custom"],
    ]),
  },
  {
    section: "reports",
    pages: [
      "/reports",
      "/reports/interview",
      "/reports/proctoring",
      "/reports/candidate",
      "/reports/analytics",
    ],
    tabs: [
      { key: "interview", path: "/reports/interview" },
      { key: "proctoring", path: "/reports/proctoring" },
      { key: "candidate", path: "/reports/candidate" },
      { key: "analytics", path: "/reports/analytics" },
    ],
  },
];

export interface ResolvedTab {
  key: string;
  section: TabbedSection;
  href: string;
  active: boolean;
}

function hrefFor(tab: TabDef): string {
  if (!tab.param?.value) return tab.path;
  return `${tab.path}?${new URLSearchParams({ [tab.param.name]: tab.param.value })}`;
}

function isActive(tab: TabDef, path: RoutePath, params: URLSearchParams): boolean {
  if (tab.path !== path) return false;
  return tab.param ? (params.get(tab.param.name) || null) === tab.param.value : true;
}

/** The tabs a page shows the session, or undefined when the page has none. */
export function tabsFor(
  path: RoutePath,
  session: Session,
  params: URLSearchParams,
): ResolvedTab[] | undefined {
  const set = TAB_SETS.find((candidate) => candidate.pages.includes(path));
  if (!set) return undefined;
  return set.tabs
    .filter((tab) => can(session, routeAt(tab.path).permission))
    .map((tab) => ({
      key: tab.key,
      section: set.section,
      href: hrefFor(tab),
      active: isActive(tab, path, params),
    }));
}
