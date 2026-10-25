import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// `findBy` and `waitFor` wait up to 5 s instead of 1 s. Rendering a whole page in jsdom can take
// longer than a second while every package's tests run at once on a busy PC (the local CI gate),
// which failed different tests on each run; the assertions themselves are unchanged.
configure({ asyncUtilTimeout: 5_000 });

vi.mock("next/navigation", async () => (await import("./src/test/navigation")).nextNavigation);

afterEach(() => {
  cleanup();
  localStorage.clear();
  for (const cookie of document.cookie.split(";")) {
    const name = cookie.split("=")[0]?.trim();
    // biome-ignore lint/suspicious/noDocumentCookie: clearing the preference cookies a test wrote.
    if (name) document.cookie = `${name}=; max-age=0; path=/`;
  }
});

// Browser APIs jsdom lacks and Radix or cmdk use.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub;
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
window.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList;
