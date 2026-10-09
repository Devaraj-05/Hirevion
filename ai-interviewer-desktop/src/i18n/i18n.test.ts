import { describe, expect, it } from "vitest";
import enIN from "./en-IN.json";
import enUS from "./en-US.json";
import { pickLocale } from "./i18n";

function keys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([key, child]) => keys(child, prefix ? `${prefix}.${key}` : key));
}

describe("languages", () => {
  it("has every message in both catalogues", () => {
    expect(keys(enUS).sort()).toEqual(keys(enIN).sort());
  });

  it("picks the candidate's language, then Windows', then en-IN", () => {
    expect(pickLocale(["en-US"])).toBe("en-US");
    expect(pickLocale(["en-us", "en-IN"])).toBe("en-US");
    expect(pickLocale(["hi-IN", "en-IN"])).toBe("en-IN");
    expect(pickLocale(["fr-FR"])).toBe("en-IN");
  });
});
