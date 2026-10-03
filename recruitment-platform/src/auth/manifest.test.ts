import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import messages from "../../messages/en-IN.json";
import { ROUTES } from "./manifest";

const SHELL = fileURLToPath(new URL("../app/recruiter/(shell)", import.meta.url));

interface PageFile {
  path: string;
  source: string;
}

function pageFiles(directory: string): PageFile[] {
  return readdirSync(directory).flatMap((name) => {
    const full = join(directory, name);
    if (statSync(full).isDirectory()) return pageFiles(full);
    if (name !== "page.tsx") return [];
    const segments = relative(SHELL, directory).split(sep).filter(Boolean);
    const path = `/${segments.filter((segment) => !segment.startsWith("(")).join("/")}`;
    return [{ path, source: readFileSync(full, "utf8") }];
  });
}

describe("the route manifest", () => {
  it("lists every guarded page, and every entry has a page", () => {
    const pages = pageFiles(SHELL).map((page) => page.path);
    expect(pages.sort()).toEqual(ROUTES.map((route) => route.path).sort());
  });

  // The proxy guard is an early answer, not the authority: a layout isn't re-rendered when
  // navigating between its pages, so every page checks its own route.
  it("has every page check its own route", () => {
    for (const page of pageFiles(SHELL)) {
      // Detail pages ("/jobs/[id]") have brackets, which a pattern reads as a character class.
      const path = page.path.replace(/[[\]]/g, "\\$&");
      const guard = new RegExp(`(requireRoute|guardedPage)\\("${path}"[,)]`);
      expect(page.source, page.path).toMatch(guard);
    }
  });

  it("has unique paths", () => {
    const paths = ROUTES.map((route) => route.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("names every route in the message catalogue", () => {
    const titles = messages.routes as Record<string, string>;
    for (const route of ROUTES) {
      expect(titles[route.titleKey], route.path).toBeTruthy();
    }
  });

  it("names the sub-project that fills each page", () => {
    for (const route of ROUTES) {
      expect(route.owner, route.path).toMatch(/^SP-\d{2}[a-z]?$/);
    }
  });
});
