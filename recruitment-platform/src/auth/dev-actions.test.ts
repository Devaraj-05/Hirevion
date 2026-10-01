import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = { set: vi.fn(), delete: vi.fn() };
vi.mock("next/headers", () => ({ cookies: async () => jar }));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`redirect:${url}`);
  },
  notFound: () => {
    throw new Error("not-found");
  },
}));

const { signInAsDevRole, signOut } = await import("./dev-actions");
const { DEV_ROLE_COOKIE } = await import("./session");

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(fields)) data.set(name, value);
  return data;
}

beforeEach(() => {
  jar.set.mockClear();
  jar.delete.mockClear();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("signInAsDevRole", () => {
  it("doesn't exist unless the development tools are on", async () => {
    await expect(signInAsDevRole(form({ role: "recruiter" }))).rejects.toThrow("not-found");
    expect(jar.set).not.toHaveBeenCalled();
  });

  it("refuses a role that isn't one of the fixtures", async () => {
    vi.stubEnv("HV_WEB_DEV_TOOLS", "true");
    await expect(signInAsDevRole(form({ role: "root" }))).rejects.toThrow("not-found");
    expect(jar.set).not.toHaveBeenCalled();
  });

  it("signs in as the role and returns to a safe path", async () => {
    vi.stubEnv("HV_WEB_DEV_TOOLS", "true");
    await expect(signInAsDevRole(form({ role: "recruiter", next: "/jobs" }))).rejects.toThrow(
      "redirect:/jobs",
    );
    expect(jar.set).toHaveBeenCalledWith(
      DEV_ROLE_COOKIE,
      "recruiter",
      expect.objectContaining({ httpOnly: true, sameSite: "lax", path: "/" }),
    );
    await expect(
      signInAsDevRole(form({ role: "recruiter", next: "https://evil.example" })),
    ).rejects.toThrow("redirect:/dashboard");
  });
});

describe("signOut", () => {
  it("forgets the development role and goes to sign in", async () => {
    await expect(signOut()).rejects.toThrow("redirect:/login");
    expect(jar.delete).toHaveBeenCalledWith(DEV_ROLE_COOKIE);
  });
});
