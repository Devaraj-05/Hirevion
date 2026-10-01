import { describe, expect, it } from "vitest";
import { hostConfig, hostKind, internalPath } from "./hosts";

const config = hostConfig({});

describe("hostKind", () => {
  it("tells the recruiter and portal hosts apart, ignoring the port and case", () => {
    expect(hostKind("app.hirevion.localhost:3000", config)).toBe("recruiter");
    expect(hostKind("APP.hirevion.localhost", config)).toBe("recruiter");
    expect(hostKind("candidate.hirevion.localhost", config)).toBe("portal");
    expect(hostKind("127.0.0.1:3000", config)).toBe("recruiter");
    expect(hostKind("[::1]:3000", config)).toBe("recruiter");
  });

  it("refuses hosts it doesn't serve", () => {
    expect(hostKind("evil.example", config)).toBe("unknown");
    expect(hostKind(null, config)).toBe("unknown");
    expect(hostKind("", config)).toBe("unknown");
  });

  it("reads the host lists from the environment", () => {
    const custom = hostConfig({
      HV_WEB_RECRUITER_HOSTS: "app.hirevion.in",
      HV_WEB_PORTAL_HOSTS: "candidate.hirevion.in, portal.hirevion.in",
    });
    expect(hostKind("portal.hirevion.in", custom)).toBe("portal");
    expect(hostKind("app.hirevion.localhost", custom)).toBe("unknown");
  });
});

describe("internalPath", () => {
  it("maps each host onto its own route tree", () => {
    expect(internalPath("recruiter", "/jobs")).toBe("/recruiter/jobs");
    expect(internalPath("portal", "/download")).toBe("/portal/download");
    expect(internalPath("recruiter", "/")).toBe("/recruiter");
    expect(internalPath("portal", "/")).toBe("/portal");
  });

  it("never lets one host address the other's tree", () => {
    expect(internalPath("portal", "/recruiter/jobs")).toBe("/portal/recruiter/jobs");
    expect(internalPath("recruiter", "/portal")).toBe("/recruiter/portal");
  });
});
