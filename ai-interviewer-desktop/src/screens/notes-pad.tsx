import { Label, Textarea } from "@hirevion/ui";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { codeBytes, DraftSaver, MAX_CODE_BYTES, type SaveStatus } from "../interview/coding";
import { commands } from "../native/commands";
import { DraftStatus } from "./draft-status";
import { ErrorText } from "./shell";

/**
 * A design question's notes pad (PRD §32's workspace for non-coding questions; product-owner
 * decision, 2026-11-15, ADR-0041): plain text the candidate types while explaining a design. It
 * is saved as the question's draft (the `whiteboard` workspace) and read by the evaluation with
 * the answer. The answer itself is still spoken (or typed in the answer box).
 */
export function NotesPad({ interviewId, questionId }: { interviewId: string; questionId: string }) {
  const t = useTranslations("notes");
  const id = useId();
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const drafts = useRef<DraftSaver | null>(null);

  // Saved while typing, on blur, and once more when the question closes (the pad unmounts).
  useEffect(() => {
    const saver = new DraftSaver({
      save: (draft) =>
        commands.saveNotes(interviewId, questionId, draft.content).then(() => undefined),
      onStatus: setStatus,
    });
    drafts.current = saver;
    return () => {
      void saver.flush().finally(() => saver.dispose());
      if (drafts.current === saver) drafts.current = null;
    };
  }, [interviewId, questionId]);

  function edit(next: string) {
    setContent(next);
    // Over the server's limit it would be refused; the pad says why instead.
    if (codeBytes(next) <= MAX_CODE_BYTES) drafts.current?.change("text", next);
  }

  const tooLarge = codeBytes(content) > MAX_CODE_BYTES;
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
        spellCheck={false}
        aria-describedby={`${id}-hint ${id}-status`}
        onChange={(event) => edit(event.target.value)}
        onBlur={() => void drafts.current?.flush()}
      />
      <DraftStatus id={`${id}-status`} status={status} />
      {tooLarge ? <ErrorText>{t("tooLarge")}</ErrorText> : null}
    </section>
  );
}
