"use client";

import { cn, Tooltip } from "@hirevion/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type { Session } from "@/auth/permissions";
import { SECTION_ICONS } from "./icons";
import { isActive, navRoutes } from "./nav";

interface SidebarProps {
  session: Session;
  /** Icons only; every link keeps its name for screen readers and shows it as a tooltip. */
  collapsed: boolean;
  onNavigate?: () => void;
}

export function Sidebar({ session, collapsed, onNavigate }: SidebarProps) {
  const pathname = usePathname();
  const t = useTranslations("shell");
  const titles = useTranslations("routes");
  return (
    <nav aria-label={t("navigation")}>
      <ul className="flex flex-col gap-0.5">
        {navRoutes(session).map((route) => {
          const Icon = SECTION_ICONS[route.section];
          const title = titles(route.titleKey);
          const active = isActive(pathname, route.path);
          const link = (
            <Link
              href={route.path}
              aria-current={active ? "page" : undefined}
              {...(onNavigate ? { onClick: onNavigate } : {})}
              className={cn(
                "flex h-9 items-center gap-3 rounded-md px-3 font-medium text-muted-foreground text-sm hover:bg-surface-muted hover:text-foreground",
                active &&
                  "bg-accent-subtle text-accent-subtle-foreground hover:bg-accent-subtle hover:text-accent-subtle-foreground",
                collapsed && "justify-center px-0",
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className={collapsed ? "sr-only" : undefined}>{title}</span>
            </Link>
          );
          return (
            <li key={route.path}>
              {collapsed ? (
                <Tooltip content={title} side="right">
                  {link}
                </Tooltip>
              ) : (
                link
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
