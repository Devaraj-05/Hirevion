import { expect, test } from "@playwright/test";
import { APP, PORTAL, signInAs } from "./support";

test("each host serves only its own pages", async ({ page, context }) => {
  await signInAs(context, "super_admin");
  expect((await page.goto(`${PORTAL}/jobs`))?.status()).toBe(404);
  expect((await page.goto(`${APP}/download`))?.status()).toBe(404);
  expect((await page.goto(`${PORTAL}/download`))?.status()).toBe(200);
});

test("a host it doesn't serve is refused", async ({ request }) => {
  const response = await request.get("http://127.0.0.1:3100/dashboard", {
    headers: { host: "evil.example" },
  });
  expect(response.status()).toBe(421);
});

test("pages carry the security headers and a fresh CSP nonce", async ({ request }) => {
  const first = await request.get(`${APP}/login`);
  const second = await request.get(`${APP}/login`);
  const csp = first.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toMatch(/'nonce-[^']+'/);
  expect(second.headers()["content-security-policy"]).not.toBe(csp);
  expect(first.headers()["x-content-type-options"]).toBe("nosniff");
  expect(first.headers()["referrer-policy"]).toBe("strict-origin-when-cross-origin");
});
