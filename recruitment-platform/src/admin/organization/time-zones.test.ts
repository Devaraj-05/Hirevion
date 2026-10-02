import { describe, expect, it } from "vitest";
import { timeZoneOptions } from "./time-zones";

describe("timeZoneOptions", () => {
  it("names zones as IANA does now, though browsers use CLDR's older names", () => {
    const zones = timeZoneOptions("Europe/London", ["Asia/Calcutta", "Asia/Saigon", "UTC"]);
    expect(zones).toEqual(["Asia/Ho_Chi_Minh", "Asia/Kolkata", "Europe/London", "UTC"]);
  });

  it("keeps the saved zone even when the browser doesn't list it", () => {
    expect(timeZoneOptions("America/Argentina/Salta", ["UTC"])).toEqual([
      "America/Argentina/Salta",
      "UTC",
    ]);
  });

  it("lists each zone once", () => {
    expect(timeZoneOptions("Asia/Kolkata", ["Asia/Calcutta", "Asia/Kolkata"])).toEqual([
      "Asia/Kolkata",
    ]);
  });
});
