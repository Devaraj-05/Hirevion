import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { getPortalSession } from "@/portal/server";
import { SignOutButton } from "@/portal/sign-out-button";
import { LanguageSwitcher } from "@/shell/language-switcher";

const LINK =
  "rounded-md px-2 py-1 text-muted-foreground hover:bg-surface-muted hover:text-foreground";

/** The candidate portal (master plan §6.3): no recruiter navigation, just the candidate's own
 * pages, the language and sign-out. */
export default async function PortalLayout({ children }: { children: ReactNode }) {
  const app = await getTranslations("app");
  const shell = await getTranslations("shell");
  const portal = await getTranslations("portal");
  const nav = await getTranslations("portal.nav");
  const session = await getPortalSession();
  const links = session
    ? [
        { href: "/", label: nav("interviews") },
        { href: "/download", label: nav("download") },
        { href: "/requests", label: nav("requests") },
        { href: "/report", label: nav("report") },
        { href: "/notices", label: nav("notices") },
      ]
    : [
        { href: "/download", label: nav("download") },
        { href: "/notices", label: nav("notices") },
        { href: "/login", label: nav("signIn") },
      ];
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-md"
      >
        {shell("skipToContent")}
      </a>
      <header className="border-border border-b bg-surface">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2 px-4 py-2">
          <span className="font-semibold">{app("name")}</span>
          <nav aria-label={nav("label")} className="flex flex-wrap items-center gap-1 text-sm">
            {links.map((link) => (
              <Link key={link.href} href={link.href} className={LINK}>
                {link.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            {session ? <SignOutButton /> : null}
          </div>
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
        <div className="mx-auto flex max-w-3xl flex-wrap gap-4 px-4 py-4 text-muted-foreground text-sm">
          <Link href="/notices" className="hover:text-foreground">
            {portal("notices")}
          </Link>
          {session ? <span>{session.organization.support_email}</span> : null}
        </div>
      </footer>
    </div>
  );
}
