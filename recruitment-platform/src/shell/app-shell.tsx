"use client";

import {
  Breadcrumbs,
  Button,
  cn,
  IconButton,
  Sheet,
  SheetContent,
  SheetTrigger,
} from "@hirevion/ui";
import { Menu, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { routeAt } from "@/auth/manifest";
import { can, type Session } from "@/auth/permissions";
import { CommandMenu } from "./command-menu";
import { breadcrumbTrail } from "./nav";
import { NotificationsButton } from "./notifications";
import { SIDEBAR_COOKIE, writePreference } from "./preferences";
import { Sidebar } from "./sidebar";
import { useShortcuts } from "./use-shortcuts";
import { UserMenu } from "./user-menu";

interface AppShellProps {
  session: Session;
  devTools: boolean;
  /** From the hv_sidebar cookie, so the first paint matches the stored choice. */
  initialCollapsed: boolean;
  children: ReactNode;
}

const SKIP_LINK =
  "sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-md";

/** The recruiter host's frame: sidebar, top bar (breadcrumbs, search, notifications, account) and main. */
export function AppShell({ session, devTools, initialCollapsed, children }: AppShellProps) {
  const t = useTranslations("shell");
  const app = useTranslations("app");
  const titles = useTranslations("routes");
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useShortcuts({
    navigate: (path) => router.push(path),
    onPalette: () => setPaletteOpen((open) => !open),
    allowed: (path) => can(session, routeAt(path).permission),
  });

  function toggleSidebar() {
    const next = !collapsed;
    setCollapsed(next);
    writePreference(SIDEBAR_COOKIE, next ? "collapsed" : "expanded");
  }

  const trail = breadcrumbTrail(pathname).map((route) => ({
    label: titles(route.titleKey),
    href: route.path,
  }));

  return (
    <div className="flex min-h-dvh">
      <a href="#main" className={SKIP_LINK}>
        {t("skipToContent")}
      </a>
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-border border-r bg-surface md:flex",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div
          className={cn(
            "flex h-14 items-center font-semibold",
            collapsed ? "justify-center" : "px-5",
          )}
        >
          <span className={collapsed ? "sr-only" : undefined}>{app("name")}</span>
        </div>
        <div className="flex-1 overflow-y-auto px-2 py-2">
          <Sidebar session={session} collapsed={collapsed} />
        </div>
        <div className={cn("border-border border-t p-2", collapsed && "flex justify-center")}>
          <IconButton
            label={collapsed ? t("expandSidebar") : t("collapseSidebar")}
            icon={collapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
            onClick={toggleSidebar}
          />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-border border-b bg-background px-4">
          <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <SheetTrigger asChild>
              <IconButton
                className="md:hidden"
                label={t("openNavigation")}
                icon={<Menu aria-hidden />}
              />
            </SheetTrigger>
            <SheetContent title={t("navigationTitle")} closeLabel={t("close")}>
              <Sidebar
                session={session}
                collapsed={false}
                onNavigate={() => setMobileNavOpen(false)}
              />
            </SheetContent>
          </Sheet>
          {trail.length > 0 ? (
            <Breadcrumbs label={t("breadcrumb")} items={trail} linkComponent={Link} />
          ) : null}
          <div className="ml-auto flex items-center gap-1">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPaletteOpen(true)}
              className="text-muted-foreground"
            >
              <Search aria-hidden />
              <span className="hidden sm:inline">{t("searchPages")}</span>
              <kbd className="hidden rounded border border-border px-1 font-sans text-xs sm:inline">
                {t("searchShortcut")}
              </kbd>
            </Button>
            <NotificationsButton session={session} />
            <UserMenu session={session} devTools={devTools} />
          </div>
        </header>
        <main id="main" tabIndex={-1} className="flex-1 px-6 py-6 outline-none">
          {children}
        </main>
      </div>
      <CommandMenu open={paletteOpen} onOpenChange={setPaletteOpen} session={session} />
    </div>
  );
}
