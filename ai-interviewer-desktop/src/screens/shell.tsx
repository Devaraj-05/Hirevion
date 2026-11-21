import type { ReactNode } from "react";
import { useTranslations } from "use-intl";
import type { Profile } from "../native/commands";
import { PillButton } from "../ui/kit";

/**
 * The frame every screen sits in. The window itself never scrolls (a desktop app, product
 * owner, 2026-11-16): the bar stays put and a screen's content scrolls under it only when it
 * can't fit. `immersive` (the interview) hands the whole window to the screen.
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
  if (immersive) {
    return <div className="h-full overflow-hidden bg-background text-foreground">{children}</div>;
  }
  return (
    <div className="flex h-full flex-col overflow-hidden bg-background text-foreground">
      <header className="chrome z-10 flex h-14 shrink-0 items-center justify-between border-border/70 border-b px-6">
        <span className="font-semibold tracking-tight">
          {profile?.organization.name ?? t("name")}
        </span>
        {profile && onSignOut ? (
          <div className="flex items-center gap-2 text-[0.9rem]">
            <span className="text-muted-foreground">{profile.candidate.email}</span>
            <PillButton variant="quiet" className="h-8 px-3" onClick={onSignOut}>
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
