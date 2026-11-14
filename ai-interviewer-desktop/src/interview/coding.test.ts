import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CodingQuestion, CodingTelemetryEvent } from "../native/commands";
import {
  CodingTelemetry,
  codeBytes,
  DraftSaver,
  indentation,
  isRetryable,
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

  it("keeps a draft's code when its language isn't offered; only the label falls back", () => {
    const drafted = {
      ...QUESTION,
      draft: { language: "sql", content: "select 1", saved_at: "2026-11-14T10:01:00Z" },
    };
    expect(openingCode(drafted)).toEqual({ language: "python", content: "select 1" });
    const shouted = {
      ...QUESTION,
      draft: { language: "JavaScript", content: "let y;", saved_at: "2026-11-14T10:01:00Z" },
    };
    expect(openingCode(shouted)).toEqual({ language: "javascript", content: "let y;" });
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

  it("indents with four spaces at the cursor", () => {
    expect(indentation("ab", 1, 1)).toEqual({
      from: 1,
      to: 1,
      text: "    ",
      selectionStart: 5,
      selectionEnd: 5,
    });
  });

  it("indents every selected line and never deletes the selection", () => {
    // "a\nb" selected: both lines move right, the selection follows them.
    expect(indentation("a\nb\nc", 0, 3)).toEqual({
      from: 0,
      to: 3,
      text: "    a\n    b",
      selectionStart: 4,
      selectionEnd: 11,
    });
    // Part of one line: the line is indented, its text kept.
    const inLine = indentation("abcd", 1, 3);
    expect(inLine.text).toBe("    abc");
    expect(apply("abcd", inLine)).toBe("    abcd");
    // A selection ending just after a newline doesn't indent the next line.
    expect(apply("a\nb\n", indentation("a\nb\n", 0, 2))).toBe("    a\nb\n");
  });

  it("tells failures worth retrying from refusals", () => {
    expect(isRetryable({ code: "network" })).toBe(true);
    expect(isRetryable({ code: "rate-limited" })).toBe(true);
    expect(isRetryable({ code: "service-unavailable" })).toBe(true);
    expect(isRetryable(new Error("boom"))).toBe(true);
    expect(isRetryable({ code: "event-out-of-time" })).toBe(false);
    expect(isRetryable({ code: "workspace-too-large" })).toBe(false);
    expect(isRetryable({ code: "interview-not-in-progress" })).toBe(false);
  });
});

function apply(value: string, edit: { from: number; to: number; text: string }): string {
  return value.slice(0, edit.from) + edit.text + value.slice(edit.to);
}

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

  it("saves at most every 30 seconds while typing, with the latest text", async () => {
    // Product-owner decision, 2026-11-14: a draft every 30 s (plus blur and the time limit).
    const { drafts, save } = saver();
    drafts.change("python", "a");
    drafts.change("python", "ab");
    await vi.advanceTimersByTimeAsync(29_999);
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenLastCalledWith({ language: "python", content: "ab" });
    drafts.change("python", "abc");
    await vi.advanceTimersByTimeAsync(29_999);
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
    await vi.advanceTimersByTimeAsync(60_000);
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
    await vi.advanceTimersByTimeAsync(30_000);
    expect(save).toHaveBeenCalledTimes(2);
    expect(statuses.at(-1)?.kind).toBe("saved");
    drafts.dispose();
  });

  it("doesn't retry a draft the server refuses until the text changes", async () => {
    const save = vi
      .fn<(draft: { language: string; content: string }) => Promise<void>>()
      .mockRejectedValueOnce({ code: "interview-not-in-progress" })
      .mockResolvedValue(undefined);
    const { drafts, statuses } = saver(save);
    drafts.change("python", "a");
    await drafts.flush();
    expect(statuses.at(-1)?.kind).toBe("refused");
    await vi.advanceTimersByTimeAsync(90_000);
    expect(save).toHaveBeenCalledTimes(1);
    drafts.change("python", "ab");
    await vi.advanceTimersByTimeAsync(30_000);
    expect(save).toHaveBeenCalledTimes(2);
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

  it("drops a batch the server refuses for good instead of blocking the queue", async () => {
    const send = vi
      .fn<(events: CodingTelemetryEvent[]) => Promise<void>>()
      .mockRejectedValueOnce({ code: "event-out-of-time" })
      .mockResolvedValue(undefined);
    const { telemetry } = recorder(send);
    for (let index = 0; index < 201; index += 1) telemetry.clipboard("cut", index);
    await telemetry.flush();
    // The refused 200 are gone; the last event still goes.
    expect(send.mock.calls.map((call) => call[0].length)).toEqual([200, 1]);
    await telemetry.flush();
    expect(send).toHaveBeenCalledTimes(2);
    telemetry.dispose();
  });

  it("ends typing and sends what is left when the console closes", async () => {
    const { telemetry, send } = recorder();
    telemetry.start();
    telemetry.keyPressed();
    await telemetry.end();
    expect(send.mock.calls[0]?.[0].map((event) => event.kind)).toEqual([
      "typing_started",
      "typing_stopped",
    ]);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(send).toHaveBeenCalledTimes(1);
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
