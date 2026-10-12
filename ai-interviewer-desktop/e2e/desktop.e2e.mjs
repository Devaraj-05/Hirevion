// The candidate's way to "Ready", in the real app: launch → version ok → sign in → interviews →
// briefing → system check → consent → ready. Run by `pnpm e2e` (e2e/run.mjs), which starts
// tauri-driver and passes the debug build in HV_E2E_APP. The app runs on its stub backend
// (HV_DESKTOP_STUB=1: any email, password "stub") with fake camera/microphone devices and
// canned native checks, so the test needs no API, no hardware and no operator.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { Session } from "./webdriver.mjs";

const SERVER = `http://127.0.0.1:${process.env.HV_E2E_PORT ?? 4444}`;
const application = process.env.HV_E2E_APP;
assert.ok(application, "HV_E2E_APP must name the debug build (run this through `pnpm e2e`)");

/** XPath for a button by its exact visible text. */
const button = (text) => `//button[normalize-space()="${text}"]`;

/** XPath for the page heading with exactly this text. */
const heading = (text) => `//h1[normalize-space()="${text}"]`;

let session;

before(async () => {
  session = await Session.start(SERVER, application);
});

after(async () => {
  await session?.end();
});

test("launch → ready", async (t) => {
  try {
    // Launch checks the version (the stub says "ok"), then asks for the sign-in.
    await session.waitFor(heading("Sign in to your interview"), 60_000);

    // Sign in. The stub accepts any email with the password "stub".
    await (await session.find("input[type=email]")).type("asha@example.test");
    await (await session.find("input[type=password]")).type("stub");
    await session.click("button[type=submit]");

    // Interviews: the first is open now.
    await session.waitFor(heading("Your interviews"));
    await session.click(button("Start the system check"));

    // Briefing, then the system check.
    await session.waitFor(heading("Before you start"));
    await session.click(button("Continue to the system check"));
    await session.waitFor(heading("System check"));

    // The check runs the native checks (canned), then the camera and microphone on the fake
    // devices (the microphone listens for about three seconds), the network, then asks about
    // the speaker. The screen renders every result before asking.
    await session.click(button("Run the check"));
    await session.waitFor(button("Yes, I heard it"), 60_000);
    const results = await session.findAll("ul[aria-label='System check'] li");
    assert.ok(results.length >= 8, `expected the check results, got ${results.length}`);
    await session.click(button("Yes, I heard it"));

    // Consent: accept every item.
    await session.waitFor(heading("Your consent"), 30_000);
    for (const box of await session.findAll("button[role=checkbox]")) await box.click();
    await session.click(button("I agree, continue"));

    // Ready.
    await session.waitFor(heading("You're ready"));
    assert.ok(await session.find(button("Start the interview")));
  } catch (error) {
    // Keep a picture of where it stopped (uploaded by CI).
    try {
      mkdirSync("e2e/output", { recursive: true });
      writeFileSync("e2e/output/failure.png", await session.screenshot());
    } catch {
      // The screenshot is a courtesy.
    }
    t.diagnostic(String(error));
    throw error;
  }
});
