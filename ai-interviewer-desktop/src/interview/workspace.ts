import type { Connection } from "./orb-state";

/**
 * The interview screen's left column (C8-12): empty until a question needs somewhere to work. A
 * coding question opens its console (ADR-0033), a design question its notes pad (ADR-0041).
 */
export type Workspace = "code" | "notes" | null;

export function workspaceOf(question: { workspace?: string } | null | undefined): Workspace {
  if (question?.workspace === "code") return "code";
  if (question?.workspace === "whiteboard") return "notes";
  return null;
}

/** Typed answers only where speech can't be used; a coding question is answered in its console. */
export function typedAnswers(
  answerMode: string | undefined,
  connection: Connection,
  workspace: Workspace,
): boolean {
  return (answerMode === "text" || connection === "off") && workspace !== "code";
}
