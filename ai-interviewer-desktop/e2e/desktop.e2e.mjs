// The candidate's way to "Ready", in the real app: launch → version ok → sign in → interviews →
// briefing → system check → consent → ready; then the interview's coding question (ADR-0033):
// code typed in the console is saved as a draft and submitted once, and nothing runs it. Run by `pnpm e2e` (e2e/run.mjs), which starts
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

/** The text box under the label with exactly this text. */
const field = (label) => `//label[normalize-space()="${label}"]/following-sibling::textarea`;

async function keepScreenshot(t, error) {
  // Keep a picture of where it stopped (uploaded by CI).
  try {
    mkdirSync("e2e/output", { recursive: true });
    writeFileSync("e2e/output/failure.png", await session.screenshot());
  } catch {
    // The screenshot is a courtesy.
  }
  t.diagnostic(String(error));
}

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
    await keepScreenshot(t, error);
    throw error;
  }
});

test("the coding console saves the code and submits it once", async (t) => {
  try {
    // The stub's interview runs in text mode: no LiveKit, the answers go through the API.
    await session.click(button("Start the interview"));
    await session.waitFor(heading("Interview"), 60_000);

    // Question 1 is spoken-style: answer it in the text box.
    await (await session.waitFor(field("Your answer"))).type("I built an order service on a queue.");
    await session.click(button("Send answer"));

    // Question 2 is the coding question: the console opens on the starter code.
    await session.waitFor(`//h2[normalize-space()="Your code"]`);
    const code = await session.waitFor(field("Code"));
    assert.match(await code.property("value"), /def two_sum/);
    await code.type("    seen = {}
");

    // The draft is saved within a few seconds (the server keeps it if time runs out).
    await session.waitFor(`//p[starts-with(normalize-space(), "Saved at")]`, 20_000);

    // One Submit, confirmed; the interview moves on to question 3.
    await session.click(button("Submit code"));
    await session.click(button("Submit now"));
    await session.waitFor(`//span[normalize-space()="Question 3"]`, 20_000);
    assert.equal((await session.findAll(`//h2[normalize-space()="Your code"]`)).length, 0);
  } catch (error) {
    await keepScreenshot(t, error);
    throw error;
  }
});
