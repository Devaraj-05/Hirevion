import type { ReactNode } from "react";
import { useTranslations } from "use-intl";
import type { Profile } from "../native/commands";
import { Wordmark } from "../ui/emblem";
import { PillButton } from "../ui/kit";

/**
 * The frame every screen sits in. The window itself never scrolls (a desktop app, product
 * owner, 2026-11-16): the bar stays put and a screen's content scrolls under it only when it
 * can't fit. `immersive` (the interview) hands the whole window to the screen. Every screen
 * shares the interview's ground and its floating bar with the mark (one theme, 2026-11-26).
 */
export function Shell({
  profile,
  onSignOut,
  immersive = false,
  children,
}: {
  profile?: Profile | undefined;
  onSignOut?: (() => void) | undefined;
  immersive?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("app");
  const interview = useTranslations("interview");
  if (immersive) {
    return <div className="app-ground h-full overflow-hidden text-foreground">{children}</div>;
  }
  return (
    <div className="app-ground flex h-full flex-col overflow-hidden text-foreground">
      <header className="app-bar">
        <Wordmark label={interview("wordmark")} className="shrink-0" />
        {profile ? (
          <>
            <span aria-hidden className="top-bar-rule h-7" />
            <span className="app-bar-org">{profile.organization.name}</span>
          </>
        ) : (
          <span className="sr-only">{t("name")}</span>
        )}
        {profile && onSignOut ? (
          <div className="ml-auto flex min-w-0 items-center gap-2 text-[0.9rem]">
            <span className="truncate text-muted-foreground max-md:sr-only">
              {profile.candidate.email}
            </span>
            <PillButton variant="quiet" className="h-9 shrink-0 px-4" onClick={onSignOut}>
              {t("signOut")}
            </PillButton>
          </div>
        ) : null}
      </header>
      <main className="relative min-h-0 flex-1 scroll-pt-6 scroll-pb-28 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col px-6 py-8">
          {children}
        </div>
      </main>
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-[0.9rem] text-danger">
      {children}
    </p>
  );
}
