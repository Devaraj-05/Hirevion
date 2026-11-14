import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CodingQuestion, CodingTelemetryEvent } from "../native/commands";
import {
  CodingTelemetry,
  codeBytes,
  DraftSaver,
  indent,
  languageName,
  MAX_CODE_BYTES,
  openingCode,
  questionSecondsLeft,
  type SaveStatus,
  switchLanguage,
} from "./coding";

const QUESTION: CodingQuestion = {
  question_id: "q1",
  text: "Write two_sum.",
  languages: ["python", "javascript"],
  starter_code: { python: "def two_sum(nums, target):\n    pass\n", javascript: "" },
  time_limit_seconds: 600,
  asked_at: "2026-11-14T10:00:00Z",
  draft: null,
};

describe("the code in the box", () => {
  it("opens on the saved draft, else on the first language's starter code", () => {
    expect(openingCode(QUESTION)).toEqual({
      language: "python",
      content: "def two_sum(nums, target):\n    pass\n",
    });
    const drafted = {
      ...QUESTION,
      draft: { language: "javascript", content: "let x = 1;", saved_at: "2026-11-14T10:01:00Z" },
    };
    expect(openingCode(drafted)).toEqual({ language: "javascript", content: "let x = 1;" });
  });

  it("ignores a draft in a language the question no longer offers", () => {
    const drafted = {
      ...QUESTION,
      draft: { language: "sql", content: "select 1", saved_at: "2026-11-14T10:01:00Z" },
    };
    expect(openingCode(drafted).language).toBe("python");
  });

  it("swaps in starter code only over an empty box or untouched starter code", () => {
    const starter = QUESTION.starter_code.python ?? "";
    expect(switchLanguage(QUESTION, "", "javascript", "python")).toBe(starter);
    expect(switchLanguage(QUESTION, starter, "python", "javascript")).toBe("");
    expect(switchLanguage(QUESTION, "my own code", "python", "javascript")).toBe("my own code");
  });

  it("names the languages and measures code in UTF-8 bytes", () => {
    expect(languageName("javascript")).toBe("JavaScript");
    expect(languageName("sql")).toBe("SQL");
    expect(languageName("cobol")).toBe("cobol");
    expect(codeBytes("é")).toBe(2);
    expect(MAX_CODE_BYTES).toBe(262_144);
  });

  it("indents with four spaces at the cursor, over a selection", () => {
    expect(indent("ab", 1, 1)).toEqual({ value: "a    b", cursor: 5 });
    expect(indent("abcd", 1, 3)).toEqual({ value: "a    d", cursor: 5 });
  });
});

describe("the question's clock", () => {
  it("counts down by the server's clock and stops at zero", () => {
    const asked = Date.parse(QUESTION.asked_at);
    // This PC is 1.5 s behind the server.
    expect(questionSecondsLeft(QUESTION, asked + 60_000 - 1_500, 1_500)).toBe(540);
    expect(questionSecondsLeft(QUESTION, asked + 700_000, 0)).toBe(0);
    expect(questionSecondsLeft({ ...QUESTION, time_limit_seconds: null }, asked, 0)).toBeNull();
  });
});

describe("DraftSaver", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function saver(
    save = vi.fn<(draft: { language: string; content: string }) => Promise<void>>(
      async () => undefined,
    ),
  ) {
    const statuses: SaveStatus[] = [];
    const drafts = new DraftSaver({ save, onStatus: (status) => statuses.push(status) });
    return { drafts, save, statuses };
  }

  it("saves at most every five seconds, with the latest text", async () => {
    const { drafts, save } = saver();
    drafts.change("python", "a");
    drafts.change("python", "ab");
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenLastCalledWith({ language: "python", content: "ab" });
    drafts.change("python", "abc");
    await vi.advanceTimersByTimeAsync(4_999);
    expect(save).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(save).toHaveBeenCalledTimes(2);
    drafts.dispose();
  });

  it("doesn't save text it has already saved", async () => {
    const { drafts, save } = saver();
    drafts.change("python", "x");
    await drafts.flush();
    drafts.change("python", "x");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(save).toHaveBeenCalledTimes(1);
    drafts.dispose();
  });

  it("saves at once on flush (blur, the time limit, Submit)", async () => {
    const { drafts, save, statuses } = saver();
    drafts.change("javascript", "let a;");
    await drafts.flush();
    expect(save).toHaveBeenCalledWith({ language: "javascript", content: "let a;" });
    expect(statuses.map((status) => status.kind)).toEqual(["saving", "saved"]);
    drafts.dispose();
  });

  it("keeps a failed draft and tries again", async () => {
    const save = vi
      .fn<(draft: { language: string; content: string }) => Promise<void>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(undefined);
    const { drafts, statuses } = saver(save);
    drafts.change("python", "a");
    await drafts.flush();
    expect(statuses.at(-1)?.kind).toBe("failed");
    await vi.advanceTimersByTimeAsync(5_000);
    expect(save).toHaveBeenCalledTimes(2);
    expect(statuses.at(-1)?.kind).toBe("saved");
    drafts.dispose();
  });
});

describe("CodingTelemetry", () => {
  const AT = Date.parse("2026-11-14T10:00:00Z");
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(AT);
  });
  afterEach(() => vi.useRealTimers());

  function recorder(
    send = vi.fn<(events: CodingTelemetryEvent[]) => Promise<void>>(async () => undefined),
  ) {
    const telemetry = new CodingTelemetry({ send, clock: () => Date.now() + 1_000 });
    return { telemetry, send };
  }

  it("marks typing started on the first key and stopped after a two-second pause", async () => {
    const { telemetry, send } = recorder();
    telemetry.keyPressed();
    await vi.advanceTimersByTimeAsync(1_000);
    telemetry.keyPressed();
    await vi.advanceTimersByTimeAsync(2_000);
    await telemetry.flush();
    expect(send).toHaveBeenCalledWith([
      { kind: "typing_started", at: "2026-11-14T10:00:01.000Z" },
      // Stopped at the last key, by the server's clock.
      { kind: "typing_stopped", at: "2026-11-14T10:00:02.000Z" },
    ]);
    telemetry.dispose();
  });

  it("sends clipboard lengths, never text, and focus changes", async () => {
    const { telemetry, send } = recorder();
    telemetry.focus();
    telemetry.clipboard("paste", 120);
    telemetry.clipboard("copy", 0);
    telemetry.blur();
    await telemetry.flush();
    const events = send.mock.calls[0]?.[0] ?? [];
    expect(events.map((event) => [event.kind, event.chars])).toEqual([
      ["focus", undefined],
      ["paste", 120],
      ["copy", 0],
      ["blur", undefined],
    ]);
    for (const event of events)
      expect(Object.keys(event).sort()).toEqual(
        event.chars === undefined ? ["at", "kind"] : ["at", "chars", "kind"],
      );
    telemetry.dispose();
  });

  it("ends typing when the box loses focus", async () => {
    const { telemetry, send } = recorder();
    telemetry.keyPressed();
    telemetry.blur();
    await telemetry.flush();
    expect(send.mock.calls[0]?.[0].map((event) => event.kind)).toEqual([
      "typing_started",
      "typing_stopped",
      "blur",
    ]);
    telemetry.dispose();
  });

  it("sends in batches of at most 200 and keeps a failed batch for later", async () => {
    const send = vi
      .fn<(events: CodingTelemetryEvent[]) => Promise<void>>()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(undefined);
    const { telemetry } = recorder(send);
    for (let index = 0; index < 250; index += 1) telemetry.clipboard("copy", index);
    await telemetry.flush();
    expect(send.mock.calls.map((call) => call[0].length)).toEqual([200, 50]);
    // The second batch failed: it goes again, first, on the next flush.
    await telemetry.flush();
    expect(send.mock.calls.at(-1)?.[0].map((event) => event.chars)).toEqual(
      Array.from({ length: 50 }, (_, index) => 200 + index),
    );
    telemetry.dispose();
  });

  it("flushes on its own every ten seconds once started", async () => {
    const { telemetry, send } = recorder();
    telemetry.start();
    telemetry.focus();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(send).toHaveBeenCalledTimes(1);
    telemetry.dispose();
    telemetry.blur();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
