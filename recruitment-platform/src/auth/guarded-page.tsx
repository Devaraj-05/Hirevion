import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Forbidden } from "./forbidden";
import { type RoutePath, routeAt } from "./manifest";
import { requireRoute } from "./server";

/** A page that checks its manifest route, then shows its title. Task-specific pages replace it. */
export function guardedPage(path: RoutePath) {
  const route = routeAt(path);
  return async function GuardedPage() {
    const session = await requireRoute(path);
    if (!session) return <Forbidden />;
    const t = await getTranslations("routes");
    return <h1 className="font-semibold text-xl">{t(route.titleKey)}</h1>;
  };
}

export function routeMetadata(path: RoutePath) {
  const route = routeAt(path);
  return async function generateMetadata(): Promise<Metadata> {
    const t = await getTranslations("routes");
    return { title: t(route.titleKey) };
  };
}
