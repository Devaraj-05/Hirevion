import { Button, Label, Textarea } from "@hirevion/ui";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { codeBytes, DraftSaver, MAX_CODE_BYTES, type SaveStatus } from "../interview/coding";
import { commands } from "../native/commands";
import { DraftStatus } from "./draft-status";
import { ErrorText } from "./shell";

/** Lets the interview screen save what is unsaved before it ends the interview. */
export type RegisterFlush = (flush: () => Promise<void>) => () => void;

/**
 * A design question's notes pad (PRD §32's workspace for non-coding questions; product-owner
 * decision, 2026-11-15, ADR-0041): plain text the candidate types while explaining a design. It
 * is saved as the question's draft (the `whiteboard` workspace) and read by the evaluation with
 * the answer. The answer itself is still spoken (or typed in the answer box). The pad opens on
 * the last saved notes (after a restart, or a follow-up's parent's), and stays read-only until
 * they are loaded, so a fresh save never hides earlier notes.
 */
export function NotesPad({
  interviewId,
  questionId,
  registerFlush,
}: {
  interviewId: string;
  questionId: string;
  registerFlush: RegisterFlush;
}) {
  const t = useTranslations("notes");
  const id = useId();
  const [content, setContent] = useState("");
  const [loaded, setLoaded] = useState<"loading" | "ready" | "failed">("loading");
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [tooLarge, setTooLarge] = useState(false);
  const drafts = useRef<DraftSaver | null>(null);

  const load = useCallback(async () => {
    setLoaded("loading");
    try {
      const answer = await commands.workspaceDraft(interviewId, questionId);
      setContent(answer.draft?.content ?? "");
      setLoaded("ready");
    } catch {
      setLoaded("failed");
    }
  }, [interviewId, questionId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Saved while typing, on blur, before the interview ends, and when the question closes.
  useEffect(() => {
    const saver = new DraftSaver({
      save: (draft) =>
        commands.saveNotes(interviewId, questionId, draft.content).then(() => undefined),
      onStatus: setStatus,
    });
    drafts.current = saver;
    const unregister = registerFlush(() => saver.flush());
    return () => {
      unregister();
      void saver.flush().finally(() => saver.dispose());
      if (drafts.current === saver) drafts.current = null;
    };
  }, [interviewId, questionId, registerFlush]);

  function edit(next: string) {
    setContent(next);
    // Over the server's limit it would be refused; the pad says why instead.
    const big = codeBytes(next) > MAX_CODE_BYTES;
    setTooLarge(big);
    if (!big) drafts.current?.change("text", next);
  }

  return (
    <section
      className="grid gap-2 rounded-md border border-border p-4"
      aria-labelledby={`${id}-title`}
    >
      <h2 id={`${id}-title`} className="font-semibold">
        {t("title")}
      </h2>
      <p id={`${id}-hint`} className="text-muted-foreground text-sm">
        {t("hint")}
      </p>
      <Label htmlFor={`${id}-notes`}>{t("label")}</Label>
      <Textarea
        id={`${id}-notes`}
        className="font-mono text-sm"
        rows={10}
        value={content}
        readOnly={loaded !== "ready"}
        spellCheck={false}
        aria-describedby={`${id}-hint ${id}-status`}
        onChange={(event) => edit(event.target.value)}
        onBlur={() => void drafts.current?.flush()}
      />
      {loaded === "failed" ? (
        <div className="flex flex-wrap items-center gap-2">
          <ErrorText>{t("loadFailed")}</ErrorText>
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            {t("retry")}
          </Button>
        </div>
      ) : null}
      {loaded === "loading" ? (
        <p className="text-muted-foreground text-sm">{t("loading")}</p>
      ) : (
        <DraftStatus id={`${id}-status`} status={status} />
      )}
      {tooLarge ? <ErrorText>{t("tooLarge")}</ErrorText> : null}
    </section>
  );
}
