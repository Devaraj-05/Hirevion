import { EmptyState } from "@hirevion/ui";
import { Construction } from "lucide-react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PORTAL_OWNER, type PortalPageKey } from "./pages";

/** A portal page awaiting SP-07: its title and an empty state naming the sub-project. */
export function portalPage(key: PortalPageKey) {
  return async function PortalPage() {
    const t = await getTranslations("portal.pages");
    const placeholder = await getTranslations("placeholder");
    return (
      <>
        <h1 className="mb-6 font-semibold text-2xl tracking-tight">{t(key)}</h1>
        <EmptyState
          icon={<Construction />}
          title={placeholder("title")}
          description={placeholder("description", { owner: PORTAL_OWNER })}
        />
      </>
    );
  };
}

export function portalMetadata(key: PortalPageKey) {
  return async function generateMetadata(): Promise<Metadata> {
    const t = await getTranslations("portal.pages");
    // Invitation links carry a token; keep every portal page out of search engines.
    return { title: t(key), robots: { index: false, follow: false } };
  };
}
