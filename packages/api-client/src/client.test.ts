import { describe, expect, it } from "vitest";
import { createApiClient, newIdempotencyKey } from "./client";
import { ApiProblem, isApiProblem } from "./problem";

type FakeFetch = (request: Request) => Promise<Response>;

function respondWith(response: Response): { fetch: FakeFetch; requests: Request[] } {
  const requests: Request[] = [];
  return {
    requests,
    fetch: async (request) => {
      requests.push(request);
      return response;
    },
  };
}

async function failure(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("expected the call to fail");
}

describe("createApiClient", () => {
  it("returns data for a successful call", async () => {
    const { fetch, requests } = respondWith(Response.json({ status: "ok" }));
    const client = createApiClient({ baseUrl: "https://api.hirevion.localhost", fetch });
    const { data } = await client.GET("/api/v1/health/live");
    expect(data).toEqual({ status: "ok" });
    expect(requests[0]?.url).toBe("https://api.hirevion.localhost/api/v1/health/live");
  });

  it("throws problem responses as ApiProblem", async () => {
    const body = {
      type: "urn:hirevion:problem:not-found",
      title: "Not Found",
      status: 404,
      code: "not-found",
      trace_id: "0af7651916cd43dd8448eb211c80319c",
    };
    const { fetch } = respondWith(
      new Response(JSON.stringify(body), {
        status: 404,
        headers: { "content-type": "application/problem+json" },
      }),
    );
    const client = createApiClient({ baseUrl: "https://api.hirevion.localhost", fetch });
    const error = await failure(client.GET("/api/v1/health/live"));

    expect(isApiProblem(error)).toBe(true);
    const problem = error as ApiProblem;
    expect(problem.status).toBe(404);
    expect(problem.code).toBe("not-found");
    expect(problem.traceId).toBe(body.trace_id);
    expect(problem.message).toBe("Not Found");
    expect(problem.raw).toEqual(body);
  });

  it("turns a non-problem failure into an ApiProblem too", async () => {
    const { fetch } = respondWith(new Response("upstream down", { status: 502 }));
    const client = createApiClient({ baseUrl: "https://api.hirevion.localhost", fetch });
    const problem = (await failure(client.GET("/api/v1/health/live"))) as ApiProblem;
    expect(problem).toBeInstanceOf(ApiProblem);
    expect(problem.code).toBe("bad-gateway");
    expect(problem.status).toBe(502);
    expect(problem.traceId).toBeNull();
  });
});

describe("newIdempotencyKey", () => {
  it("makes a fresh UUID each time", () => {
    const key = newIdempotencyKey();
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(newIdempotencyKey()).not.toBe(key);
  });
});
