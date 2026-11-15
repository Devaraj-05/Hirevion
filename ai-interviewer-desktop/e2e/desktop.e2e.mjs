// The candidate's way to "Ready", in the real app: launch → version ok → sign in → interviews →
// briefing → system check → consent → phone (third eye) → ready; then the interview's coding
// question (ADR-0033): code typed in the console is saved as a draft and submitted once, and
// nothing runs it; then a design question's notes pad (ADR-0041). Run by `pnpm e2e`
// (e2e/run.mjs), which starts tauri-driver and passes the debug build in HV_E2E_APP. The app
// runs on its stub backend
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

async function keepScreenshot(t, error, name) {
  // Keep a picture of where it stopped, one per test (CI uploads the folder).
  try {
    mkdirSync("e2e/output", { recursive: true });
    writeFileSync(`e2e/output/failure-${name}.png`, await session.screenshot());
  } catch {
    // The screenshot is a courtesy.
  }
  t.diagnostic(String(error));
}

let session;
/** The coding test goes on from where "launch → ready" stops; without it, it is skipped. */
let ready = false;

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

    // Consent: one Terms and Conditions checkbox accepts every item (owner, 2026-11-15).
    await session.waitFor(heading("Your consent"), 30_000);
    const boxes = await session.findAll("button[role=checkbox]");
    assert.equal(boxes.length, 1, "one checkbox, for the Terms and Conditions");
    await boxes[0].click();
    await session.click(button("Continue"));

    // The phone as a third eye (the stub's interview offers one): a QR code with where to put
    // the phone under it, then the stub phone scans it and its camera connects within a few
    // status reads.
    await session.waitFor(heading("Connect your phone"), 30_000);
    assert.ok(await session.find("svg[role=img] path"), "the QR code is drawn");
    assert.ok(
      await session.find(`//figure/following::h2[normalize-space()="Where to put your phone"]`),
      "where to put the phone is shown under the code",
    );
    await session.waitFor(`//p[starts-with(normalize-space(), "Phone connected")]`, 20_000);
    // C8-3: the phone's picture must show the candidate and the whole laptop (the stub's phone
    // "films" both), and the candidate confirms it; Continue stays off until then.
    const proceed = await session.find(button("Continue"));
    assert.equal(await proceed.property("disabled"), true, "Continue waits for the green zone");
    await session.waitFor(`//p[starts-with(normalize-space(), "In the green zone")]`, 20_000);
    const [confirm] = await session.findAll("button[role=checkbox]");
    await confirm.click();
    await session.click(button("Continue"));

    // Ready.
    await session.waitFor(heading("You're ready"));
    assert.ok(await session.find(button("Start the interview")));
    ready = true;
  } catch (error) {
    await keepScreenshot(t, error, "ready");
    throw error;
  }
});

test("the coding console and the design notes pad keep the candidate's work", async (t) => {
  if (!ready) {
    t.skip('needs "launch → ready" to reach the Ready screen');
    return;
  }
  try {
    // The stub's interview runs in text mode: no LiveKit, the answers go through the API.
    await session.click(button("Start the interview"));
    await session.waitFor(heading("Interview"), 60_000);

    // The phone paired before Ready stays in view: the status bar shows its camera.
    await session.waitFor(`//*[normalize-space()="Phone camera: connected"]`, 15_000);

    // Question 1 is spoken-style: answer it in the text box.
    await (await session.waitFor(field("Your answer"))).type(
      "I built an order service on a queue.",
    );
    await session.click(button("Send answer"));

    // Question 2 is the coding question: the console opens on the starter code.
    await session.waitFor(`//h2[normalize-space()="Your code"]`);
    const code = await session.waitFor(field("Code"));
    assert.match(await code.property("value"), /def two_sum/);
    await code.type("    seen = {}\n");

    // While typing, the draft is saved every 30 s (the server keeps it if time runs out).
    await session.waitFor(`//p[starts-with(normalize-space(), "Saved at")]`, 45_000);

    // One Submit, confirmed; the interview moves on to question 3.
    await session.click(button("Submit code"));
    await session.click(button("Submit now"));
    await session.waitFor(`//span[normalize-space()="Question 3"]`, 20_000);
    assert.equal((await session.findAll(`//h2[normalize-space()="Your code"]`)).length, 0);

    // Question 3 is answered in the text box; question 4 is a design question with the notes
    // pad (ADR-0041).
    await (await session.waitFor(field("Your answer"))).type("I would read traces and slow logs.");
    await session.click(button("Send answer"));
    await session.waitFor(`//h2[normalize-space()="Design notes"]`, 20_000);
    await (await session.waitFor(field("Your design notes"))).type(
      "Client -> API -> idempotency keys table -> payment provider",
    );
    // Leaving the pad saves the notes at once.
    const answer = await session.find(field("Your answer"));
    await answer.click();
    await session.waitFor(`//p[starts-with(normalize-space(), "Saved at")]`, 15_000);
    await answer.type("Every request carries an idempotency key the server remembers.");
    await session.click(button("Send answer"));

    // That was the last question.
    await session.waitFor(heading("Thank you"), 30_000);
  } catch (error) {
    await keepScreenshot(t, error, "coding");
    throw error;
  }
});
