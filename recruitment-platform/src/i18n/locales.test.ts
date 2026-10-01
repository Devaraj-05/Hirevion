import { createFormatter } from "next-intl";
import { describe, expect, it } from "vitest";
import enIN from "../../messages/en-IN.json";
import enUS from "../../messages/en-US.json";
import { DEFAULT_LOCALE, LOCALES, resolveLocale } from "./locales";

type Catalogue = { [key: string]: string | Catalogue };

function keys(catalogue: Catalogue, prefix = ""): string[] {
  return Object.entries(catalogue).flatMap(([key, value]) =>
    typeof value === "string" ? [`${prefix}${key}`] : keys(value, `${prefix}${key}.`),
  );
}

function values(catalogue: Catalogue): string[] {
  return Object.values(catalogue).flatMap((value) =>
    typeof value === "string" ? [value] : values(value),
  );
}

describe("message catalogues", () => {
  it("have the same keys in every locale", () => {
    expect(keys(enUS).sort()).toEqual(keys(enIN).sort());
  });

  it("have no empty messages", () => {
    for (const catalogue of [enIN, enUS]) {
      expect(values(catalogue).filter((value) => value.trim() === "")).toEqual([]);
    }
  });
});

describe("locales", () => {
  it("defaults to Indian English and ignores unknown values", () => {
    expect(DEFAULT_LOCALE).toBe("en-IN");
    expect(LOCALES).toEqual(["en-IN", "en-US"]);
    expect(resolveLocale("en-US")).toBe("en-US");
    expect(resolveLocale("fr-FR")).toBe("en-IN");
    expect(resolveLocale(undefined)).toBe("en-IN");
  });

  it("groups digits the Indian way for en-IN", () => {
    expect(createFormatter({ locale: "en-IN" }).number(1234567)).toBe("12,34,567");
    expect(createFormatter({ locale: "en-US" }).number(1234567)).toBe("1,234,567");
  });
});
