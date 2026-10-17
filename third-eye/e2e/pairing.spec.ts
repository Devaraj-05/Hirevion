import { createHmac, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page, test } from "@playwright/test";

/**
 * The phone's pairing, as a phone would do it: open the QR code's URL, redeem, allow the camera,
 * publish. The API's answers come from the test; LiveKit is the real local server.
 *
 * Pairing time: from opening the page to the camera being live (the page's "Paired in"). The
 * server's share (issue, redeem, the webhook) is measured in `test_third_eye_api.py`.
 */

const PAIRING_BUDGET_S = 60;

function livekitKeys(): { key: string; secret: string } | null {
  const fromEnv = (name: string) => process.env[name];
  let key = fromEnv("LIVEKIT_API_KEY");
  let secret = fromEnv("LIVEKIT_API_SECRET");
  if (!key || !secret) {
    try {
      const env = readFileSync(resolve(import.meta.dirname, "../../.env"), "utf8");
      for (const line of env.split(/\r?\n/)) {
        const [name, ...rest] = line.split("=");
        const value = rest.join("=").trim().replace(/^"|"$/g, "");
        if (name?.trim() === "LIVEKIT_API_KEY") key = value;
        if (name?.trim() === "LIVEKIT_API_SECRET") secret = value;
      }
    } catch {
      return null;
    }
  }
  return key && secret ? { key, secret } : null;
}

const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");

/** A camera-only participant token, exactly as the API's `third_eye_token` grants it. */
function phoneToken(key: string, secret: string, room: string, identity: string): string {
  const now = Math.floor(Date.now() / 1000);
  const body = encode({
    iss: key,
    sub: identity,
    name: "Third eye",
    nbf: now,
    exp: now + 600,
    video: {
      roomJoin: true,
      room,
      canPublish: true,
      canSubscribe: false,
      canPublishData: false,
      canPublishSources: ["camera"],
    },
  });
  const unsigned = `${encode({ alg: "HS256", typ: "JWT" })}.${body}`;
  return `${unsigned}.${createHmac("sha256", secret).update(unsigned).digest("base64url")}`;
}

function joinAnswer(token: string, identity: string, livekitUrl: string | null) {
  return {
    pairing_id: identity.replace("third-eye-", ""),
    livekit_url: livekitUrl,
    participant_token: token,
    participant_identity: identity,
    expires_at: new Date(Date.now() + 600_000).toISOString(),
    device_token: `device-${randomUUID()}`,
    interview: { company: "Acme", job_title: "Backend Engineer" },
    placement: { distance_m: 1.5, angle: "side-rear", show: ["face", "hands", "desk", "screen"] },
  };
}

async function answerRedeem(page: Page, status: number, body: unknown): Promise<string[]> {
  const sent: string[] = [];
  await page.route("**/api/v1/third-eye/redeem", async (route) => {
    sent.push(route.request().postData() ?? "");
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  return sent;
}

test("a used QR code is explained, and the token leaves the address bar", async ({ page }) => {
  const sent = await answerRedeem(page, 410, { code: "token-used" });
  await page.goto(`/#t=${"a".repeat(43)}`);
  await expect(page.getByRole("alert")).toContainText("already used");
  expect(JSON.parse(sent[0] ?? "{}").token).toBe("a".repeat(43));
  expect(new URL(page.url()).hash).toBe("");
});

test("the phone shows the placement guide before the camera starts", async ({ page }) => {
  await answerRedeem(page, 200, joinAnswer("unused", `third-eye-${randomUUID()}`, null));
  await page.goto(`/#t=${"b".repeat(43)}`);
  await expect(page.getByRole("heading", { name: "Place this phone" })).toBeVisible();
  await expect(page.getByText("Acme · Backend Engineer")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start camera" })).toBeVisible();
});

test("pairing to a live rear camera takes under 60 s, and a lock pauses it", async ({ page }) => {
  const keys = livekitKeys();
  test.skip(keys === null, "needs the local LiveKit (uv run hv up) and its keys in .env");
  if (keys === null) return;
  const identity = `third-eye-${randomUUID()}`;
  const room = `iv-${randomUUID()}`;
  const token = phoneToken(keys.key, keys.secret, room, identity);
  await answerRedeem(page, 200, joinAnswer(token, identity, "ws://127.0.0.1:7880"));

  await page.goto(`/#t=${"c".repeat(43)}&auto=1`);
  const status = page.getByRole("status").filter({ hasText: "Live" });
  await expect(status).toBeVisible({ timeout: PAIRING_BUDGET_S * 1000 });
  const pairedIn = Number.parseFloat((await page.getByTestId("paired-in").textContent()) ?? "");
  console.log(`Paired in ${pairedIn.toFixed(1)} s (budget ${PAIRING_BUDGET_S} s)`);
  expect(pairedIn).toBeLessThan(PAIRING_BUDGET_S);

  // The phone locks: the page unpublishes its camera at once, then publishes again.
  const setVisibility = (state: "hidden" | "visible") =>
    page.evaluate((value) => {
      Object.defineProperty(document, "visibilityState", { value, configurable: true });
      document.dispatchEvent(new Event("visibilitychange"));
    }, state);
  await setVisibility("hidden");
  await expect(page.locator("[data-state=paused]")).toBeVisible();
  await setVisibility("visible");
  await expect(page.locator("[data-state=live]")).toBeVisible({ timeout: 15_000 });
});
