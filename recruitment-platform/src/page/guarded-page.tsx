import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ComponentType } from "react";
import { Forbidden } from "@/auth/forbidden";
import { type RoutePath, routeAt } from "@/auth/manifest";
import { requireRoute } from "@/auth/server";
import { type PageBodyProps, PlaceholderBody } from "./bodies";
import { PageHeader } from "./page-header";
import { RouteTabs } from "./route-tabs";

type RawSearchParams = Record<string, string | string[] | undefined>;

function toSearchParams(raw: RawSearchParams): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(raw)) {
    for (const item of [value].flat()) if (item !== undefined) params.append(key, item);
  }
  return params;
}

/**
 * A page that checks its manifest route, then renders its title, its section's tabs and a body
 * (by default the placeholder naming the sub-project that fills it).
 */
export function guardedPage(path: RoutePath, Body: ComponentType<PageBodyProps> = PlaceholderBody) {
  const route = routeAt(path);
  return async function GuardedPage({ searchParams }: { searchParams: Promise<RawSearchParams> }) {
    const session = await requireRoute(path);
    if (!session) return <Forbidden />;
    const params = toSearchParams(await searchParams);
    const titles = await getTranslations("routes");
    return (
      <>
        <PageHeader title={titles(route.titleKey)} />
        <RouteTabs path={path} session={session} params={params} />
        <Body session={session} route={route} params={params} />
      </>
    );
  };
}

export function routeMetadata(path: RoutePath) {
  const route = routeAt(path);
  return async function generateMetadata(): Promise<Metadata> {
    const t = await getTranslations("routes");
    return { title: t(route.titleKey) };
  };
}
