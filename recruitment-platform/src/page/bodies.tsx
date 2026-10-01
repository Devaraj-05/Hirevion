import { EmptyState } from "@hirevion/ui";
import { BellOff, Construction } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { type ManifestRoute, ROUTES } from "@/auth/manifest";
import { can, type Session } from "@/auth/permissions";

/** What a guarded page renders below its header and tabs. */
export interface PageBodyProps {
  session: Session;
  route: ManifestRoute;
  params: URLSearchParams;
}

/** Until a page's sub-project lands: an empty state naming it. */
export async function PlaceholderBody({ route }: PageBodyProps) {
  const t = await getTranslations("placeholder");
  return (
    <EmptyState
      icon={<Construction />}
      title={t("title")}
      description={t("description", { owner: route.owner })}
    />
  );
}

/** A section's own page: links to the section's pages the session may open. */
export async function SectionIndexBody({ session, route }: PageBodyProps) {
  const titles = await getTranslations("routes");
  const pages = ROUTES.filter(
    (entry) => entry.section === route.section && entry !== route && can(session, entry.permission),
  );
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {pages.map((page) => (
        <li key={page.path}>
          <Link
            href={page.path}
            className="block rounded-lg border border-border bg-surface p-4 font-medium hover:border-accent"
          >
            {titles(page.titleKey)}
          </Link>
        </li>
      ))}
    </ul>
  );
}

export async function NotificationsBody() {
  const t = await getTranslations("shell.notifications");
  return <EmptyState icon={<BellOff />} title={t("empty")} description={t("emptyHint")} />;
}
