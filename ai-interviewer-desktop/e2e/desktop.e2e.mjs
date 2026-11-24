// The candidate's way to the interview, in the real app: launch → version ok → sign in →
// interviews → the one page before the interview (camera and microphone, system check, Terms
// and Conditions, phone as a third eye; owner, 2026-11-16) → start; then the interview's coding
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
    await session.click(button("Get ready"));

    // Everything before the interview is one page of four steps, each opening after the last.
    await session.waitFor(heading("Get ready for your interview"));
    const start = await session.find(button("Start interview"));
    assert.equal(await start.property("disabled"), true, "Start waits for every step");

    // 1. Camera and microphone: allowed (fake devices), seen, then Continue.
    await session.click(button("Allow access"));
    await session.waitFor(button("Continue"), 20_000);
    await session.click(button("Continue"));

    // 2. The system check starts by itself: the native checks (canned), then the camera and
    // microphone on the fake devices (the microphone listens for about three seconds), the
    // network, then it asks about the speaker.
    await session.waitFor(button("Yes, I heard it"), 60_000);
    // The camera, microphone, network and display show first; the other checks run unseen and
    // show only when they fail (owner, 2026-11-21), so a passing one never does.
    const results = await session.findAll("ul[aria-label='System check'] li");
    const shown = await Promise.all(results.map((row) => row.text()));
    const first = ["Camera", "Microphone", "Network", "Displays"];
    first.forEach((name, index) => {
      assert.ok(shown[index]?.trim().startsWith(name), `row ${index + 1} is ${shown[index]}`);
    });
    assert.ok(!shown.some((row) => row.trim().startsWith("Processor")), "a passing check shows");
    await session.click(button("Yes, I heard it"));

    // Then the running apps (ADR-0046; the stub finds ChatGPT on the first look): a blocked app
    // keeps the step open until it is closed; other open apps are advice.
    await session.waitFor(`//p[normalize-space()="Close these apps to continue"]`, 30_000);
    await session.find(`//li[contains(normalize-space(), "ChatGPT")]`);
    await session.click(button("Check again"));
    await session.waitFor(`//p[normalize-space()="Close your other apps"]`, 30_000);
    await session.click(button("Continue"));

    // 3. One Terms and Conditions checkbox accepts every item (owner, 2026-11-15).
    await session.waitFor(
      `//label[starts-with(normalize-space(), "I have read and agree")]`,
      30_000,
    );
    // A firm warning comes before the agreement (owner, 2026-11-21).
    await session.find(`//p[normalize-space()="This interview is monitored"]`);
    const boxes = await session.findAll("button[role=checkbox]");
    assert.equal(boxes.length, 1, "one checkbox, for the Terms and Conditions");
    await boxes[0].click();

    // 4. The phone as a third eye (the stub's interview needs one): a QR code beside where to
    // put the phone; the stub phone scans it and its camera connects within a few reads.
    await session.waitFor("svg[role=img] path", 30_000);
    assert.ok(
      await session.find(`//h3[normalize-space()="Where to put your phone"]`),
      "where to put the phone is shown beside the code",
    );
    // C8-3: the phone's picture must show the candidate and the whole laptop (the stub's phone
    // "films" both), and the candidate confirms it before the step is done.
    await session.waitFor(`//p[starts-with(normalize-space(), "In the green zone")]`, 30_000);
    const placed = await session.find(button("Confirm placement"));
    assert.equal(await placed.property("disabled"), true, "confirming waits for the tick");
    const [confirm] = await session.findAll("button[role=checkbox]");
    await confirm.click();
    await session.click(button("Confirm placement"));

    // Every step done: Start opens.
    await session.waitFor(`//*[normalize-space()="You're all set."]`);
    assert.equal(await (await session.find(button("Start interview"))).property("disabled"), false);
    ready = true;
  } catch (error) {
    await keepScreenshot(t, error, "ready");
    throw error;
  }
});

test("the coding console and the design notes pad keep the candidate's work", async (t) => {
  if (!ready) {
    t.skip('needs "launch → ready" to reach the Start button');
    return;
  }
  try {
    // The stub's interview runs in text mode: no LiveKit, the answers go through the API.
    await session.click(button("Start interview"));
    // The interview fills the window (C8-12): the bar names the interview and keeps the time and
    // End interview at the top right.
    await session.waitFor(button("End interview"), 60_000);
    await session.waitFor(`//h1[contains(normalize-space(), "– Interview")]`);
    assert.match(await (await session.find("header time")).text(), /^\d\d:\d\d$/);

    // End interview asks first; Continue keeps the interview going.
    await session.click(button("End interview"));
    await session.waitFor(heading("End the interview?"));
    await session.click(button("Continue interview"));
    await session.waitFor(button("End interview"));

    // The cameras: the main one and the phone set up before the start, each with the mark.
    await session.waitFor(`//figure[@data-kind="main"]`);
    await session.waitFor(`//figure[@data-kind="side"][@data-status="ok"]`, 15_000);
    assert.equal(
      (await session.findAll(`//span[normalize-space()="Confidential • Interview session"]`))
        .length,
      2,
    );

    // A spoken-style question leaves the coding area empty.
    await session.waitFor(`//p[normalize-space()="When a coding question is asked, it opens here."]`);

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

    // One Submit, confirmed; the interview moves on to question 3, answered in the text box.
    await session.click(button("Submit code"));
    await session.click(button("Submit now"));
    await session.waitFor(field("Your answer"), 20_000);
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
    // One attempt (C8-9): only a way out, never back into the interviews.
    assert.equal((await session.findAll(button("Close app"))).length, 1);
    assert.equal((await session.findAll(button("Back to your interviews"))).length, 0);
  } catch (error) {
    await keepScreenshot(t, error, "coding");
    throw error;
  }
});
