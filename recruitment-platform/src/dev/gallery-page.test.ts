import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not-found");
  },
}));
vi.mock("./gallery", () => ({ Gallery: () => null }));

const { default: GalleryPage } = await import("../app/recruiter/dev/ui/page");

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("the component gallery page", () => {
  it("doesn't exist without the development tools", () => {
    vi.stubEnv("HV_WEB_DEV_TOOLS", "false");
    expect(() => GalleryPage()).toThrow("not-found");
  });

  it("renders the gallery when they are on", () => {
    vi.stubEnv("HV_WEB_DEV_TOOLS", "true");
    expect(GalleryPage()).toBeTruthy();
  });
});
