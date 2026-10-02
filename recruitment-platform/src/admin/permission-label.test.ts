import { describe, expect, it } from "vitest";
import { PERMISSIONS } from "@/auth/permissions";
import enIN from "../../messages/en-IN.json";
import enUS from "../../messages/en-US.json";
import { permissionArea, permissionLabelKey } from "./permission-label";

describe("permission labels", () => {
  for (const [locale, catalogue] of [
    ["en-IN", enIN],
    ["en-US", enUS],
  ] as const) {
    it(`name every permission, and only those, in ${locale}`, () => {
      const labels: Record<string, string> = catalogue.permissionLabels;
      expect(Object.keys(labels).sort()).toEqual(PERMISSIONS.map(permissionLabelKey).sort());
    });

    it(`head every area in ${locale}`, () => {
      const areas: Record<string, string> = catalogue.permissionAreas;
      expect(Object.keys(areas).sort()).toEqual(
        [...new Set(PERMISSIONS.map(permissionArea))].sort(),
      );
    });
  }

  it("turn dots into underscores, since the catalogue nests on dots", () => {
    expect(permissionLabelKey("admin.api_keys.manage")).toBe("admin_api_keys_manage");
    expect(permissionArea("reports.interview.view")).toBe("reports");
  });
});
