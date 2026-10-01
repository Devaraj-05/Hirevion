import { expect, test } from "@playwright/test";
import { signInAs } from "./support";

test.beforeEach(async ({ context }) => {
  await signInAs(context, "recruiter");
});

test("the skip link comes first and moves focus to the content", async ({ page }) => {
  await page.goto("/dashboard");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main#main")).toBeFocused();
});

test("the sidebar is reachable with Tab", async ({ page }) => {
  await page.goto("/dashboard");
  const jobs = page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Jobs" });
  for (
    let presses = 0;
    presses < 15 && !(await jobs.evaluate((link) => link === document.activeElement));
    presses++
  ) {
    await page.keyboard.press("Tab");
  }
  await expect(jobs).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/jobs$/);
});

test("Ctrl+K opens the palette, Escape closes it and focus returns", async ({ page }) => {
  await page.goto("/dashboard");
  const search = page.getByRole("button", { name: /Search pages/ });
  await search.focus();
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Go to" });
  await expect(palette).toBeVisible();
  await page.keyboard.type("candidates");
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(search).toBeFocused();

  await page.keyboard.press("Control+k");
  await page.keyboard.type("question library");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/questions$/);
});

test("g then a letter goes to a section", async ({ page }) => {
  await page.goto("/dashboard");
  await page.locator("main#main").focus();
  await page.keyboard.press("g");
  await page.keyboard.press("i");
  await expect(page).toHaveURL(/\/interviews$/);
});

test("the account menu opens with Enter and closes with Escape", async ({ page }) => {
  await page.goto("/dashboard");
  const account = page.getByRole("button", { name: "Your account" });
  await account.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toBeHidden();
  await expect(account).toBeFocused();
});

test("switching the language re-renders the page in it", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByRole("menuitemradio", { name: "English (United States)" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en-US");
});

test("the development role switcher keeps you on the page", async ({ page }) => {
  await page.goto("/candidates");
  await page.getByRole("button", { name: "Your account" }).click();
  await page.getByRole("menuitemradio", { name: "Interviewer" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "You don't have access to this page",
  );
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link")).toHaveCount(3);
});
