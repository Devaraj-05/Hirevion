import { describe, expect, it, vi } from "vitest";
import { PairingError, redeem, rejoin, roomUrl } from "./api";

const joined = {
  pairing_id: "p-1",
  livekit_url: null,
  participant_token: "lk-token",
  participant_identity: "third-eye-p-1",
  expires_at: "2026-10-12T05:10:00Z",
  device_token: "device-secret",
  interview: { company: "Acme", job_title: "Backend Engineer" },
  placement: { distance_m: 1.5, angle: "side-rear", show: ["face", "hands", "desk", "screen"] },
};

function answer(status: number, body: unknown): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
}

describe("redeem", () => {
  it("spends the token once and sends the browser's user agent", async () => {
    const fetcher = answer(200, joined);
    const result = await redeem("pairing-token", "Mozilla/5.0 (iPhone)", fetcher);
    expect(result.participant_token).toBe("lk-token");
    const [url, init] = vi.mocked(fetcher).mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/third-eye/redeem");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      token: "pairing-token",
      device: { user_agent: "Mozilla/5.0 (iPhone)" },
    });
  });

  it.each([
    ["token-used", "already used"],
    ["token-expired", "expired"],
    ["pairing-revoked", "cancelled"],
    ["pairing-not-found", "isn't valid"],
  ])("explains %s", async (code, words) => {
    const failed = redeem("t", "ua", answer(code === "pairing-not-found" ? 404 : 410, { code }));
    await expect(failed).rejects.toBeInstanceOf(PairingError);
    await expect(failed).rejects.toThrow(words);
  });

  it("says when the service is down", async () => {
    await expect(redeem("t", "ua", answer(503, {}))).rejects.toThrow("try again");
  });
});

describe("rejoin", () => {
  it("exchanges the device secret for a new LiveKit token", async () => {
    const fetcher = answer(200, { ...joined, device_token: null });
    await rejoin("device-secret", fetcher);
    const [url, init] = vi.mocked(fetcher).mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/third-eye/rejoin");
    expect(JSON.parse(String(init?.body))).toEqual({ device_token: "device-secret" });
  });

  it("marks a revoked pairing as final", async () => {
    const failed = rejoin("d", answer(410, { code: "pairing-revoked" }));
    await expect(failed).rejects.toMatchObject({ final: true });
  });
});

describe("roomUrl", () => {
  it("uses the server's LiveKit address, or this page's origin which proxies /rtc", () => {
    expect(roomUrl("wss://livekit.example.test", "eye.example.test")).toBe(
      "wss://livekit.example.test",
    );
    expect(roomUrl(null, "abc.trycloudflare.com")).toBe("wss://abc.trycloudflare.com");
  });
});
