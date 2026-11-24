import { CodeXml } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslations } from "use-intl";

/**
 * The left column (C8-12, owner's reference 2026-11-24): the coding question's card. Until the AI
 * asks a coding (or design) question it says the question will appear here; then it holds the
 * question and its console or notes pad, sliding in from the left edge.
 */
export function WorkspaceColumn({ children }: { children: ReactNode | null }) {
  const t = useTranslations("interview.workspace");
  const open = children !== null;
  return (
    <section
      className={`card workspace-pane ${open ? "workspace-open" : "workspace-idle"}`}
      aria-label={t("label")}
    >
      <header className="card-header">
        <CodeXml aria-hidden className="size-5 text-foreground" strokeWidth={2} />
        <h2 className="card-title">{t("title")}</h2>
        <span className="card-pill">{open ? t("inProgress") : t("waiting")}</span>
      </header>
      {open ? (
        <div className="workspace-scroll">{children}</div>
      ) : (
        <div className="workspace-empty">
          <CodingIllustration />
          <p className="workspace-empty-title">{t("emptyTitle")}</p>
          <p className="workspace-empty-body">{t("emptyBody")}</p>
        </div>
      )}
      <Waves />
    </section>
  );
}

/** An open laptop with a code mark and a few sparkles: drawn for this screen. */
function CodingIllustration() {
  return (
    <svg viewBox="0 0 240 150" aria-hidden className="coding-illustration">
      <rect x="62" y="34" width="116" height="78" rx="9" className="ill-screen" />
      <rect x="70" y="42" width="100" height="62" rx="5" className="ill-glass" />
      <path d="M44 114h152a4 4 0 0 1-4 6H48a4 4 0 0 1-4-6z" className="ill-base" />
      <rect x="104" y="114" width="32" height="3" rx="1.5" className="ill-notch" />
      <path d="M106 63l-10 10 10 10M134 63l10 10-10 10M126 59l-12 28" className="ill-code" />
      <path d="M40 34l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" className="ill-spark" />
      <path d="M196 20l2.5 7 7 2.5-7 2.5-2.5 7-2.5-7-7-2.5 7-2.5z" className="ill-spark" />
      <path d="M205 52l1.5 4 4 1.5-4 1.5-1.5 4-1.5-4-4-1.5 4-1.5z" className="ill-spark" />
      <circle cx="30" cy="58" r="2" className="ill-spark" />
      <circle cx="186" cy="56" r="1.6" className="ill-spark" />
    </svg>
  );
}

/** The soft waves along the bottom of a card. */
export function Waves() {
  return (
    <svg viewBox="0 0 400 80" preserveAspectRatio="none" aria-hidden className="card-waves">
      <path d="M0 52 C 90 20, 170 70, 260 44 S 360 30, 400 40 V80 H0z" className="wave-back" />
      <path d="M0 62 C 110 40, 200 82, 300 58 S 380 52, 400 56 V80 H0z" className="wave-front" />
    </svg>
  );
}
