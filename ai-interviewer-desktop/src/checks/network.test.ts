import { describe, expect, it } from "vitest";
import { networkResult } from "./network";

describe("the network check", () => {
  it("passes a quick round trip to the interview service", () => {
    expect(networkResult(120)).toEqual({
      check: "network",
      status: "pass",
      value: "120 ms to the interview service",
    });
  });

  it("warns on a slow round trip, and fails a very slow or missing one", () => {
    expect(networkResult(300).status).toBe("warn");
    expect(networkResult(999).status).toBe("warn");
    expect(networkResult(1000).status).toBe("fail");
    expect(networkResult(null)).toMatchObject({
      status: "fail",
      detail: expect.stringContaining("internet"),
    });
  });
});
