import type { CodingQuestion, CodingTelemetryEvent } from "../native/commands";

/**
 * The coding console's logic (ADR-0033, contract coding.md): a plain text box whose code is
 * saved as the candidate types and submitted once. Nothing here runs the code, and nothing
 * records keystrokes or clipboard text: the integrity events carry kinds, times and lengths.
 */

/** The server's limit on code and drafts: 256 KB of UTF-8. */
export const MAX_CODE_BYTES = 256 * 1024;
/** At most one draft save in this many milliseconds (the server allows 30 a minute). */
export const DRAFT_INTERVAL_MS = 5_000;
/** Typing stops after this pause; the next key starts it again. */
export const TYPING_PAUSE_MS = 2_000;
/** Queued integrity events are sent this often, in batches of at most `MAX_BATCH`. */
export const TELEMETRY_FLUSH_MS = 10_000;
export const MAX_BATCH = 200;
/** Events kept while offline; past this the oldest are dropped. */
const MAX_QUEUED = 5_000;
const INDENT = "    ";

const LANGUAGE_NAMES: Record<string, string> = {
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
  sql: "SQL",
};

export function languageName(language: string): string {
  return LANGUAGE_NAMES[language] ?? language;
}

export function codeBytes(code: string): number {
  return new TextEncoder().encode(code).length;
}

export interface CodeInBox {
  language: string;
  content: string;
}

/** What the box holds when the console opens: the saved draft (after a restart), else the
 * first language with its starter code. A draft's code is always kept; when its language
 * isn't one the question offers, only the label falls back to the first one. */
export function openingCode(question: CodingQuestion): CodeInBox {
  const first = question.languages[0] ?? "";
  const draft = question.draft;
  if (draft) {
    const wanted = draft.language.toLowerCase();
    const offered = question.languages.find((language) => language.toLowerCase() === wanted);
    return { language: offered ?? first, content: draft.content };
  }
  return { language: first, content: question.starter_code[first] ?? "" };
}

/** Problem codes that may pass on their own: offline, rate-limited, the server busy. A
 * refusal (anything else from the server) isn't sent again unchanged. */
const TRANSIENT = new Set([
  "network",
  "rate-limited",
  "service-unavailable",
  "internal-error",
  "unexpected-response",
  "token-invalid",
  "signed-out",
]);

export function isRetryable(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return true;
  const code = (error as { code?: unknown }).code;
  return typeof code !== "string" || TRANSIENT.has(code);
}

/** The box after the candidate picks another language: that language's starter code when the
 * box is empty or still holds the previous language's starter code untouched; the
 * candidate's own text otherwise (the language is only a label). */
export function switchLanguage(
  question: CodingQuestion,
  content: string,
  from: string,
  to: string,
): string {
  const untouched = content.trim() === "" || content === (question.starter_code[from] ?? "");
  return untouched ? (question.starter_code[to] ?? "") : content;
}

/** One replacement in the box: `value[from:to]` becomes `text`, then the selection. */
export interface BoxEdit {
  from: number;
  to: number;
  text: string;
  selectionStart: number;
  selectionEnd: number;
}

/** Tab in the box: four spaces at the cursor, or, with a selection, four spaces at the start
 * of every line it touches. Selected text is never replaced. */
export function indentation(value: string, start: number, end: number): BoxEdit {
  if (start === end) {
    const at = start + INDENT.length;
    return { from: start, to: end, text: INDENT, selectionStart: at, selectionEnd: at };
  }
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const lines = value.slice(lineStart, end).split("\n");
  // A selection that ends just after a newline doesn't take in the next line.
  const last = lines.length > 1 && lines[lines.length - 1] === "" ? lines.length - 1 : lines.length;
  const text = lines.map((line, index) => (index < last ? INDENT + line : line)).join("\n");
  return {
    from: lineStart,
    to: end,
    text,
    selectionStart: start + INDENT.length,
    selectionEnd: end + INDENT.length * last,
  };
}

/** Whole seconds left on the question by the server's clock; null when it has no limit. */
export function questionSecondsLeft(
  question: Pick<CodingQuestion, "asked_at" | "time_limit_seconds">,
  nowMs: number,
  serverOffsetMs: number,
): number | null {
  if (question.time_limit_seconds == null) return null;
  const deadline = Date.parse(question.asked_at) + question.time_limit_seconds * 1000;
  return Math.max(0, Math.floor((deadline - (nowMs + serverOffsetMs)) / 1000));
}

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; at: number }
  /** It will try again. */
  | { kind: "failed" }
  /** The server refused this text; the next change is tried. */
  | { kind: "refused" };

export interface DraftSaverOptions {
  save(draft: CodeInBox): Promise<void>;
  onStatus(status: SaveStatus): void;
  intervalMs?: number;
}

function same(a: CodeInBox | null, b: CodeInBox): boolean {
  return a !== null && a.language === b.language && a.content === b.content;
}

/**
 * Saves the box's latest text as the question's draft: at most once per interval while the
 * candidate types, at once on `flush()` (blur, just before the time limit, before Submit),
 * and again after a failure that may pass. Text it has saved, or that the server refused,
 * isn't sent again.
 */
export class DraftSaver {
  private latest: CodeInBox | null = null;
  private saved: CodeInBox | null = null;
  private refused: CodeInBox | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running: Promise<void> | null = null;
  private disposed = false;
  private readonly intervalMs: number;

  constructor(private readonly options: DraftSaverOptions) {
    this.intervalMs = options.intervalMs ?? DRAFT_INTERVAL_MS;
  }

  change(language: string, content: string): void {
    this.latest = { language, content };
    if (this.pending()) this.schedule();
  }

  /** Saves now if there is unsaved text, after any save already on its way. */
  async flush(): Promise<void> {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    while (this.running) await this.running;
    if (!this.pending() || this.disposed) return;
    this.running = this.saveLatest();
    try {
      await this.running;
    } finally {
      this.running = null;
    }
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private pending(): boolean {
    const latest = this.latest;
    return latest !== null && !same(this.saved, latest) && !same(this.refused, latest);
  }

  private schedule(): void {
    if (this.timer !== null || this.disposed) return;
    // An interval after the first unsaved change: while the candidate types, a save every
    // interval at most.
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, this.intervalMs);
  }

  private async saveLatest(): Promise<void> {
    const draft = this.latest;
    if (draft === null) return;
    this.options.onStatus({ kind: "saving" });
    try {
      await this.options.save(draft);
      this.saved = draft;
      this.options.onStatus({ kind: "saved", at: Date.now() });
    } catch (error) {
      if (isRetryable(error)) {
        this.options.onStatus({ kind: "failed" });
      } else {
        this.refused = draft;
        this.options.onStatus({ kind: "refused" });
      }
    }
    // Text typed during the save, or a failed save, goes in the next interval.
    if (this.pending()) this.schedule();
  }
}

export interface CodingTelemetryOptions {
  send(events: CodingTelemetryEvent[]): Promise<void>;
  /** Milliseconds since the epoch by the server's clock (`GET /time`). */
  clock(): number;
}

/**
 * The console's integrity events (PRD §48, the text box only). It notes that typing started
 * and stopped, never which keys; that text was pasted, copied or cut, and how long it was,
 * never the text; and focus changes. Events queue while offline and go in order, in
 * batches of at most 200.
 */
export class CodingTelemetry {
  private queue: CodingTelemetryEvent[] = [];
  private typing = false;
  private lastKeyAt = 0;
  private pauseTimer: ReturnType<typeof setTimeout> | null = null;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private sending: Promise<void> | null = null;

  constructor(private readonly options: CodingTelemetryOptions) {}

  /** Sends what is queued every ten seconds until `dispose()`. */
  start(): void {
    if (this.flushTimer !== null) return;
    this.flushTimer = setInterval(() => void this.flush(), TELEMETRY_FLUSH_MS);
  }

  /** A key went down in the box. Which key is never looked at or kept. */
  keyPressed(): void {
    this.lastKeyAt = this.options.clock();
    if (!this.typing) {
      this.typing = true;
      this.push({ kind: "typing_started", at: iso(this.lastKeyAt) });
    }
    if (this.pauseTimer !== null) clearTimeout(this.pauseTimer);
    this.pauseTimer = setTimeout(() => this.stopTyping(), TYPING_PAUSE_MS);
  }

  /** Text was pasted, copied or cut: only its length is kept. */
  clipboard(kind: "paste" | "copy" | "cut", chars: number): void {
    this.push({ kind, at: iso(this.options.clock()), chars: Math.max(0, Math.floor(chars)) });
  }

  focus(): void {
    this.push({ kind: "focus", at: iso(this.options.clock()) });
  }

  blur(): void {
    this.stopTyping();
    this.push({ kind: "blur", at: iso(this.options.clock()) });
  }

  /** Sends the queue in order; a batch that fails stays first in line for the next flush. */
  async flush(): Promise<void> {
    while (this.sending) await this.sending;
    this.sending = this.sendQueued();
    try {
      await this.sending;
    } finally {
      this.sending = null;
    }
  }

  /** The console is closing: typing (if any) stops now, what is queued is sent, and the
   * timers stop. */
  async end(): Promise<void> {
    this.stopTyping();
    await this.flush();
    this.dispose();
  }

  /** Stops the timers. Call `flush()` first to send what is left. */
  dispose(): void {
    if (this.pauseTimer !== null) clearTimeout(this.pauseTimer);
    if (this.flushTimer !== null) clearInterval(this.flushTimer);
    this.pauseTimer = null;
    this.flushTimer = null;
  }

  private stopTyping(): void {
    if (this.pauseTimer !== null) clearTimeout(this.pauseTimer);
    this.pauseTimer = null;
    if (!this.typing) return;
    this.typing = false;
    // Typing stopped at the last key, not when the pause was noticed.
    this.push({ kind: "typing_stopped", at: iso(this.lastKeyAt) });
  }

  private push(event: CodingTelemetryEvent): void {
    this.queue.push(event);
    if (this.queue.length > MAX_QUEUED) this.queue.splice(0, this.queue.length - MAX_QUEUED);
  }

  private async sendQueued(): Promise<void> {
    while (this.queue.length > 0) {
      const batch = this.queue.slice(0, MAX_BATCH);
      try {
        await this.options.send(batch);
      } catch (error) {
        // Offline or busy: the batch stays at the front for the next flush. Refused for good
        // (a time out of range, the interview over): it is dropped so the rest can go.
        if (isRetryable(error)) return;
      }
      this.queue.splice(0, batch.length);
    }
  }
}

function iso(ms: number): string {
  return new Date(ms).toISOString();
}
