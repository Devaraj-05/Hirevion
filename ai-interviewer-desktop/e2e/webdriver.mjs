// A minimal W3C WebDriver client over fetch: just what the desktop end-to-end test needs.
// It talks to `tauri-driver`, which starts msedgedriver, which starts the app's WebView2.
// (WebdriverIO would do, but it brings hundreds of packages for a dozen calls.)

const ELEMENT = "element-6066-11e4-a52e-4f735466cecf";

export class WebDriverError extends Error {}

export class Session {
  constructor(server, id) {
    this.server = server;
    this.id = id;
  }

  /** Starts the app (`application` is the .exe) and returns the session. */
  static async start(server, application) {
    const response = await call(server, "POST", "/session", {
      capabilities: {
        alwaysMatch: {
          browserName: "webview2",
          "tauri:options": { application },
          "wdio:enforceWebDriverClassic": true,
        },
      },
    });
    return new Session(server, response.sessionId);
  }

  async request(method, path, body) {
    return call(this.server, method, `/session/${this.id}${path}`, body);
  }

  /** The first element matching a CSS selector or, when it starts with `/`, an XPath. */
  async find(selector) {
    const using = selector.startsWith("/") ? "xpath" : "css selector";
    const element = await this.request("POST", "/element", { using, value: selector });
    return new Element(this, element[ELEMENT]);
  }

  async findAll(selector) {
    const using = selector.startsWith("/") ? "xpath" : "css selector";
    const elements = await this.request("POST", "/elements", { using, value: selector });
    return elements.map((element) => new Element(this, element[ELEMENT]));
  }

  /** Retries `find` until the element is displayed, or throws after `timeout` ms. */
  async waitFor(selector, timeout = 20_000) {
    const deadline = Date.now() + timeout;
    let last;
    while (Date.now() < deadline) {
      try {
        const element = await this.find(selector);
        if (await element.displayed()) return element;
      } catch (error) {
        last = error;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new WebDriverError(
      `timed out after ${timeout} ms waiting for ${selector}: ${last ?? ""}`,
    );
  }

  async click(selector, timeout) {
    await (await this.waitFor(selector, timeout)).click();
  }

  async screenshot() {
    return Buffer.from(await this.request("GET", "/screenshot"), "base64");
  }

  async end() {
    await call(this.server, "DELETE", `/session/${this.id}`).catch(() => undefined);
  }
}

class Element {
  constructor(session, id) {
    this.session = session;
    this.id = id;
  }

  request(method, path, body) {
    return this.session.request(method, `/element/${this.id}${path}`, body);
  }

  click() {
    return this.request("POST", "/click", {});
  }

  text() {
    return this.request("GET", "/text");
  }

  displayed() {
    return this.request("GET", "/displayed");
  }

  type(text) {
    return this.request("POST", "/value", { text });
  }
}

async function call(server, method, path, body) {
  const response = await fetch(`${server}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) {
    const { error, message } = json.value ?? {};
    throw new WebDriverError(`${method} ${path}: ${error ?? response.status} ${message ?? ""}`);
  }
  return json.value;
}
