import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import enIN from "../../messages/en-IN.json";
import enUS from "../../messages/en-US.json";
import { PORTAL_PAGES } from "./pages";

const PORTAL = fileURLToPath(new URL("../app/portal", import.meta.url));

function pagePaths(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const full = join(directory, name);
    if (statSync(full).isDirectory()) return pagePaths(full);
    if (name !== "page.tsx") return [];
    return [`/${relative(PORTAL, directory).split(sep).filter(Boolean).join("/")}`];
  });
}

describe("the candidate portal (master plan §6.3)", () => {
  it("has exactly the listed pages", () => {
    expect(pagePaths(PORTAL).sort()).toEqual(PORTAL_PAGES.map((page) => page.path).sort());
  });

  it("names every page in both languages", () => {
    for (const page of PORTAL_PAGES) {
      expect(enIN.portal.pages[page.key], page.key).toBeTruthy();
      expect(enUS.portal.pages[page.key], page.key).toBeTruthy();
    }
  });
});
