import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import type { PortalPageKey } from "./pages";

export function portalMetadata(key: PortalPageKey) {
  return async function generateMetadata(): Promise<Metadata> {
    const t = await getTranslations("portal.pages");
    // Invitation links carry a token; keep every portal page out of search engines.
    return { title: t(key), robots: { index: false, follow: false } };
  };
}

/** A portal page's title and, below it, an optional introduction. */
export async function PortalHeading({ page, intro }: { page: PortalPageKey; intro?: ReactNode }) {
  const t = await getTranslations("portal.pages");
  return (
    <div className="mb-6 grid gap-2">
      <h1 className="font-semibold text-2xl tracking-tight">{t(page)}</h1>
      {intro ? <p className="text-muted-foreground">{intro}</p> : null}
    </div>
  );
}

/** The sign-in and emailed-link pages: one narrow card. */
export function PortalCard({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-sm flex-col gap-6 rounded-lg border border-border bg-surface p-6 shadow-sm">
      {children}
    </div>
  );
}
