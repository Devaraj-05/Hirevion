import { getTranslations } from "next-intl/server";
import { ROUTES, type RoutePath, routeAt } from "@/auth/manifest";
import type { Session } from "@/auth/permissions";
import { SectionTabs } from "./section-tabs";
import { tabsFor } from "./tabs";

export async function RouteTabs({
  path,
  session,
  params,
}: {
  path: RoutePath;
  session: Session;
  params: URLSearchParams;
}) {
  const tabs = tabsFor(path, session, params);
  if (!tabs?.length) return null;
  const t = await getTranslations("tabs");
  const titles = await getTranslations("routes");
  const section = routeAt(path).section;
  const sectionRoot =
    ROUTES.find((entry) => entry.nav && entry.section === section) ?? routeAt(path);
  return (
    <SectionTabs
      label={titles(sectionRoot.titleKey)}
      tabs={tabs.map((tab) => ({
        href: tab.href,
        // Tab keys are data in tabs.ts, so the key is built; a test checks each has a message.
        label: t(`${tab.section}.${tab.key}` as "jobs.all"),
        active: tab.active,
      }))}
    />
  );
}
