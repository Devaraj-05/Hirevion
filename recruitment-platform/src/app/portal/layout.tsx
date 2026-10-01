import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { LanguageSwitcher } from "@/shell/language-switcher";

/** The candidate portal (master plan §6.3): no recruiter navigation, just the brand and language. */
export default async function PortalLayout({ children }: { children: ReactNode }) {
  const app = await getTranslations("app");
  const shell = await getTranslations("shell");
  const portal = await getTranslations("portal");
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-md"
      >
        {shell("skipToContent")}
      </a>
      <header className="border-border border-b bg-surface">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
          <span className="font-semibold">{app("name")}</span>
          <LanguageSwitcher />
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 outline-none"
      >
        {children}
      </main>
      <footer className="border-border border-t">
        <div className="mx-auto max-w-3xl px-4 py-4 text-muted-foreground text-sm">
          <Link href="/notices" className="hover:text-foreground">
            {portal("notices")}
          </Link>
        </div>
      </footer>
    </div>
  );
}
