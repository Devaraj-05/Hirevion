import { createApiClient } from "@hirevion/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { inviteUser, listUsers } from "./api";

const requests: Request[] = [];

vi.mock("@/data/api", () => ({
  apiClient: () =>
    createApiClient({
      baseUrl: "https://app.hirevion.localhost",
      csrfToken: () => "csrf-token",
      fetch: async (request: Request) => {
        requests.push(request);
        return Response.json(
          request.method === "GET" ? { items: [], next_cursor: null } : { id: "u-1" },
          { status: request.method === "GET" ? 200 : 201 },
        );
      },
    }),
}));

beforeEach(() => {
  requests.length = 0;
});

describe("admin API calls", () => {
  it("send an invitation with its idempotency key and the CSRF token", async () => {
    const invitation = {
      email: "asha@acme.example.test",
      name: "Asha Rao",
      role_ids: ["r-1"],
      access_scope: "organization" as const,
      locale: "en-IN" as const,
    };
    await inviteUser(invitation, "key-0001");
    await inviteUser(invitation, "key-0001");
    expect(requests.map((r) => r.headers.get("Idempotency-Key"))).toEqual(["key-0001", "key-0001"]);
    expect(requests[0]?.headers.get("X-CSRF-Token")).toBe("csrf-token");
    expect(await requests[0]?.json()).toEqual(invitation);
  });

  it("leave empty filters out of the query", async () => {
    await listUsers({ q: "", status: "active", cursor: null, limit: 25 });
    expect(new URL(requests[0]?.url ?? "").search).toBe("?status=active&limit=25");
  });
});
