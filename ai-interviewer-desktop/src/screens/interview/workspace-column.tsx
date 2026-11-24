import { CodeXml } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslations } from "use-intl";

/**
 * The left column (C8-12, owner 2026-11-22: "completely empty unless a coding question is
 * asked"): a quiet pane that says what it is for, until a coding question opens its console or a
 * design question its notes pad. Its content slides in from the left edge.
 */
export function WorkspaceColumn({ children }: { children: ReactNode | null }) {
  const t = useTranslations("interview.workspace");
  if (children === null) {
    return (
      <section className="pane workspace-pane workspace-idle" aria-label={t("label")}>
        <div className="workspace-empty">
          <CodeXml aria-hidden className="size-5" strokeWidth={1.75} />
          <p>{t("empty")}</p>
        </div>
      </section>
    );
  }
  return (
    <section className="pane workspace-pane workspace-open" aria-label={t("label")}>
      <div className="workspace-scroll">{children}</div>
    </section>
  );
}
