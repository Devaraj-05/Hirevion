import { describe, expect, it, vi } from "vitest";
import { DEV_SESSIONS } from "./dev-sessions";
import { DEV_ROLE_COOKIE, resolveSession } from "./session";

const devTools = { HV_WEB_DEV_TOOLS: "true" };
const apiSession = {
  ...DEV_SESSIONS.recruiter,
  user: { id: "u-1", name: "Asha Rao", email: "asha@example.test" },
};

function respond(status: number, body?: unknown): typeof fetch {
  return vi.fn(async () =>
    body === undefined ? new Response(null, { status }) : Response.json(body, { status }),
  ) as unknown as typeof fetch;
}

describe("resolveSession", () => {
  it("uses a development session only when the tools are on", async () => {
    const cookies = { [DEV_ROLE_COOKIE]: "org_admin" };
    expect(await resolveSession(cookies, devTools, respond(404))).toEqual(DEV_SESSIONS.org_admin);
    expect(await resolveSession(cookies, {}, respond(404))).toBeNull();
  });

  it("ignores an unknown development role", async () => {
    expect(await resolveSession({ [DEV_ROLE_COOKIE]: "root" }, devTools, respond(404))).toBeNull();
  });

  it("asks the API for the session, forwarding the cookies", async () => {
    const fetcher = respond(200, apiSession);
    const session = await resolveSession(
      { hv_session: "abc" },
      { HV_API_INTERNAL_URL: "http://api.internal:8000" },
      fetcher,
    );
    // Sessions from the API are told apart from development ones.
    expect(session).toEqual({ ...apiSession, source: "api" });
    const [url, init] = (fetcher as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://api.internal:8000/api/v1/auth/session");
    expect(new Headers(init.headers).get("cookie")).toBe("hv_session=abc");
  });

  it("reads custom roles, and treats a response without them as having none", async () => {
    const { customRoles: _, ...withoutCustomRoles } = apiSession;
    const plain = await resolveSession({ hv_session: "abc" }, {}, respond(200, withoutCustomRoles));
    expect(plain?.customRoles).toEqual([]);

    const custom = await resolveSession(
      { hv_session: "abc" },
      {},
      respond(200, { ...withoutCustomRoles, custom_roles: ["Talent sourcer"] }),
    );
    expect(custom?.customRoles).toEqual(["Talent sourcer"]);
  });

  it("defaults to the API as `uv run hv api` serves it", async () => {
    const fetcher = respond(200, apiSession);
    await resolveSession({ hv_session: "abc" }, {}, fetcher);
    const [url] = (fetcher as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("http://127.0.0.1:8000/api/v1/auth/session");
  });

  it("treats any API failure as no session", async () => {
    expect(await resolveSession({ hv_session: "abc" }, {}, respond(401))).toBeNull();
    expect(await resolveSession({ hv_session: "abc" }, {}, respond(404))).toBeNull();
    const broken = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    expect(await resolveSession({ hv_session: "abc" }, {}, broken)).toBeNull();
    expect(
      await resolveSession({ hv_session: "abc" }, {}, respond(200, { nope: true })),
    ).toBeNull();
  });

  it("doesn't call the API without cookies", async () => {
    const fetcher = respond(200, apiSession);
    expect(await resolveSession({}, {}, fetcher)).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
