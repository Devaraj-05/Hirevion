import { Button } from "@hirevion/ui";
import type { ReactNode } from "react";
import { useTranslations } from "use-intl";
import type { Profile } from "../native/commands";

/** The frame every screen sits in: the app name, who is signed in, and signing out. */
export function Shell({
  profile,
  onSignOut,
  children,
}: {
  profile?: Profile | undefined;
  onSignOut?: (() => void) | undefined;
  children: ReactNode;
}) {
  const t = useTranslations("app");
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="flex items-center justify-between border-border border-b px-6 py-3">
        <span className="font-semibold">{profile?.organization.name ?? t("name")}</span>
        {profile && onSignOut ? (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-muted-foreground">{profile.candidate.email}</span>
            <Button variant="ghost" onClick={onSignOut}>
              {t("signOut")}
            </Button>
          </div>
        ) : null}
      </header>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-10">{children}</main>
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-danger text-sm">
      {children}
    </p>
  );
}
