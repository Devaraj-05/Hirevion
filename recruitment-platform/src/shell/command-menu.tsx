"use client";

import { type CommandGroup, CommandPalette } from "@hirevion/ui";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ROUTES } from "@/auth/manifest";
import type { Session } from "@/auth/permissions";
import { permittedRoutes, shortcutFor } from "./nav";

interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: Session;
}

/** Ctrl/⌘+K: every page the session may open, grouped by section. */
export function CommandMenu({ open, onOpenChange, session }: CommandMenuProps) {
  const router = useRouter();
  const t = useTranslations("shell.palette");
  const titles = useTranslations("routes");

  const groups: CommandGroup[] = [];
  for (const route of permittedRoutes(session)) {
    const sectionRoot =
      ROUTES.find((entry) => entry.nav && entry.section === route.section) ?? route;
    const heading = titles(sectionRoot.titleKey);
    let group = groups.find((candidate) => candidate.heading === heading);
    if (!group) {
      group = { heading, items: [] };
      groups.push(group);
    }
    const key = shortcutFor(route.path);
    group.items = [
      ...group.items,
      {
        id: route.path,
        label: titles(route.titleKey),
        keywords: [heading],
        ...(key ? { hint: `G ${key.toUpperCase()}` } : {}),
        onSelect: () => router.push(route.path),
      },
    ];
  }

  return (
    <CommandPalette
      open={open}
      onOpenChange={onOpenChange}
      label={t("label")}
      placeholder={t("placeholder")}
      emptyLabel={t("empty")}
      groups={groups}
    />
  );
}
