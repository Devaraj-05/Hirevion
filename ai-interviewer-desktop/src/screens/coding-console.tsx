import { Button, Label, NativeSelect, Textarea } from "@hirevion/ui";
import {
  type ClipboardEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useFormatter, useTranslations } from "use-intl";
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
} from "../interview/coding";
import { formatClock } from "../interview/session";
import {
  type CodingQuestion,
  commands,
  type InterviewState,
  isCommandError,
} from "../native/commands";
import { recordingCommands } from "../recording/native";
import { ErrorText } from "./shell";

/** Save the draft this many seconds before the question's limit: the server keeps the last
 * saved draft when time runs out. */
const SAVE_BEFORE_LIMIT_SECONDS = 5;
const SUBMIT_ERRORS = [
  "question-not-current",
  "not-a-coding-question",
  "language-not-offered",
  "code-too-large",
  "interview-not-in-progress",
  "network",
] as const;
type SubmitError = (typeof SUBMIT_ERRORS)[number] | "unknown" | "load";
/** Keys that change the text; only whether one went down is noted, never which. */
const EDITING_KEYS = new Set(["Backspace", "Delete", "Enter", "Tab"]);

function submitError(failure: unknown): SubmitError {
  if (!isCommandError(failure)) return "unknown";
  return (SUBMIT_ERRORS as readonly string[]).includes(failure.code)
    ? (failure.code as SubmitError)
    : "unknown";
}

/**
 * PRD §45, ADR-0033: the coding question's console. A plain text box (no IDE, nothing is run),
 * the language as a label, the code saved as a draft while the candidate types, and one
 * Submit. Its integrity events note typing, clipboard lengths and focus, never keys or text.
 */
export function CodingConsole({
  interviewId,
  questionId,
  onSubmitted,
  onClosed,
}: {
  interviewId: string;
  questionId: string;
  /** The submission was taken; the interview's next state. */
  onSubmitted: (next: InterviewState) => void;
  /** The question closed elsewhere (its time ran out, or it was answered): refresh the state. */
  onClosed: () => void;
}) {
  const t = useTranslations("coding");
  const format = useFormatter();
  const id = useId();
  const box = useRef<HTMLTextAreaElement | null>(null);
  const [question, setQuestion] = useState<CodingQuestion | null>(null);
  const [language, setLanguage] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<SubmitError | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const offset = useRef(0);
  const drafts = useRef<DraftSaver | null>(null);
  const telemetry = useRef<CodingTelemetry | null>(null);
  const escaped = useRef(false);
  const savedForLimit = useRef(false);
  // The latest callback, so a new one from the parent never reloads the box (and the code).
  const closed = useRef(onClosed);
  useEffect(() => {
    closed.current = onClosed;
  });

  const load = useCallback(async () => {
    setError(null);
    try {
      const clock = await recordingCommands.clock().catch(() => ({ server_offset_ms: 0 }));
      offset.current = clock.server_offset_ms;
      const answer = await commands.coding(interviewId);
      const open = answer.question;
      if (open === null || open.question_id !== questionId) {
        closed.current();
        return;
      }
      const opening = openingCode(open);
      setLanguage(opening.language);
      setContent(opening.content);
      setQuestion(open);
    } catch {
      setError("load");
    }
  }, [interviewId, questionId]);

  useEffect(() => {
    void load();
  }, [load]);

  // The draft saver and the integrity events live as long as the question is open here.
  useEffect(() => {
    if (question === null) return;
    const saver = new DraftSaver({
      save: (draft) =>
        commands
          .saveCode(interviewId, question.question_id, draft.language, draft.content)
          .then(() => undefined),
      onStatus: setStatus,
    });
    const events = new CodingTelemetry({
      send: (batch) =>
        commands.codingTelemetry(interviewId, question.question_id, batch).then(() => undefined),
      clock: () => Date.now() + offset.current,
    });
    events.start();
    drafts.current = saver;
    telemetry.current = events;
    return () => {
      void saver.flush().finally(() => saver.dispose());
      void events.flush().finally(() => events.dispose());
      if (drafts.current === saver) drafts.current = null;
      if (telemetry.current === events) telemetry.current = null;
    };
  }, [interviewId, question]);

  // The question's own clock, by the server's time.
  useEffect(() => {
    if (question === null) return;
    const update = () => setSecondsLeft(questionSecondsLeft(question, Date.now(), offset.current));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [question]);

  // Just before the limit, save what is in the box: it becomes the final code if time runs out.
  useEffect(() => {
    if (secondsLeft === null || secondsLeft > SAVE_BEFORE_LIMIT_SECONDS || savedForLimit.current)
      return;
    savedForLimit.current = true;
    void drafts.current?.flush();
  }, [secondsLeft]);

  // After Tab indents, put the cursor after the inserted spaces.
  useLayoutEffect(() => {
    if (cursor === null || box.current === null) return;
    box.current.setSelectionRange(cursor, cursor);
    setCursor(null);
  }, [cursor]);

  function edit(next: string) {
    setContent(next);
    drafts.current?.change(language, next);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const shortcut = event.ctrlKey || event.metaKey || event.altKey;
    if (!shortcut && (event.key.length === 1 || EDITING_KEYS.has(event.key))) {
      // Esc, then Tab, leaves the box as usual.
      if (!(event.key === "Tab" && escaped.current)) telemetry.current?.keyPressed();
    }
    if (event.key === "Escape") {
      escaped.current = true;
      return;
    }
    if (event.key === "Tab" && !event.shiftKey && !shortcut && !escaped.current) {
      event.preventDefault();
      const target = event.currentTarget;
      const next = indent(target.value, target.selectionStart, target.selectionEnd);
      edit(next.value);
      setCursor(next.cursor);
    }
    escaped.current = false;
  }

  function onClipboard(kind: "copy" | "cut", event: ClipboardEvent<HTMLTextAreaElement>) {
    const target = event.currentTarget;
    telemetry.current?.clipboard(kind, target.selectionEnd - target.selectionStart);
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    // Only the pasted text's length is kept; the text itself is never stored or sent.
    telemetry.current?.clipboard("paste", event.clipboardData.getData("text/plain").length);
  }

  function chooseLanguage(next: string) {
    if (question === null || next === language) return;
    const replaced = switchLanguage(question, content, language, next);
    setLanguage(next);
    setContent(replaced);
    drafts.current?.change(next, replaced);
  }

  async function submit() {
    if (question === null) return;
    setSubmitting(true);
    setError(null);
    await telemetry.current?.flush();
    try {
      const answer = await commands.submitCode(
        interviewId,
        question.question_id,
        language,
        content,
      );
      // The question is closed: nothing more to save for it.
      drafts.current?.dispose();
      onSubmitted(answer.state);
    } catch (failure) {
      const code = submitError(failure);
      setError(code);
      setSubmitting(false);
      setConfirming(false);
      if (code === "question-not-current" || code === "not-a-coding-question") closed.current();
    }
  }

  if (question === null) {
    return error === "load" ? (
      <div className="grid gap-2">
        <ErrorText>{t("errors.load")}</ErrorText>
        <Button variant="secondary" className="w-fit" onClick={() => void load()}>
          {t("retry")}
        </Button>
      </div>
    ) : (
      <p role="status" className="text-muted-foreground text-sm">
        {t("loading")}
      </p>
    );
  }

  const tooLarge = codeBytes(content) > MAX_CODE_BYTES;
  const canSubmit = content.trim() !== "" && !tooLarge && !submitting;
  return (
    <section
      className="grid gap-3 rounded-md border border-border p-4"
      aria-labelledby={`${id}-title`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={`${id}-title`} className="font-semibold">
          {t("title")}
        </h2>
        {secondsLeft !== null ? (
          <span className="font-mono">
            <span className="sr-only">{t("questionTimeLeft")} </span>
            <time>{formatClock(secondsLeft)}</time>
          </span>
        ) : null}
      </div>
      <p className="text-muted-foreground text-sm">{t("neverRun")}</p>

      <div className="grid gap-1 sm:w-60">
        <Label htmlFor={`${id}-language`}>{t("language")}</Label>
        <NativeSelect
          id={`${id}-language`}
          value={language}
          onChange={(event) => chooseLanguage(event.target.value)}
          options={question.languages.map((value) => ({ value, label: languageName(value) }))}
        />
      </div>

      <div className="grid gap-1">
        <Label htmlFor={`${id}-code`}>{t("codeLabel")}</Label>
        <Textarea
          id={`${id}-code`}
          ref={box}
          className="font-mono text-sm"
          rows={16}
          value={content}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          autoComplete="off"
          wrap="off"
          aria-describedby={`${id}-hint ${id}-status`}
          onChange={(event) => edit(event.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          onCopy={(event) => onClipboard("copy", event)}
          onCut={(event) => onClipboard("cut", event)}
          onFocus={() => telemetry.current?.focus()}
          onBlur={() => {
            telemetry.current?.blur();
            void drafts.current?.flush();
          }}
        />
        <p id={`${id}-hint`} className="text-muted-foreground text-xs">
          {t("tabHint")}
        </p>
      </div>

      <p id={`${id}-status`} role="status" className="text-muted-foreground text-sm">
        {status.kind === "saved"
          ? t("status.saved", {
              time: format.dateTime(new Date(status.at), {
                hour: "numeric",
                minute: "2-digit",
                second: "2-digit",
              }),
            })
          : t(`status.${status.kind}`)}
      </p>

      {secondsLeft === 0 ? (
        <p role="alert" className="rounded-md bg-warning-subtle p-3 text-sm text-warning">
          {t("timeUp")}
        </p>
      ) : null}
      {tooLarge ? <ErrorText>{t("errors.code-too-large")}</ErrorText> : null}
      {error ? <ErrorText>{t(`errors.${error}`)}</ErrorText> : null}

      <div className="flex flex-wrap items-center gap-2">
        {confirming ? (
          <>
            <p className="w-full text-sm">{t("submitWarning")}</p>
            <Button disabled={submitting} onClick={() => void submit()}>
              {t("submitConfirm")}
            </Button>
            <Button variant="ghost" disabled={submitting} onClick={() => setConfirming(false)}>
              {t("keepEditing")}
            </Button>
          </>
        ) : (
          <Button disabled={!canSubmit} onClick={() => setConfirming(true)}>
            {t("submit")}
          </Button>
        )}
      </div>
    </section>
  );
}
