"use client";

import {
  Avatar,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  type ThemePreference,
  useTheme,
} from "@hirevion/ui";
import { LogOut } from "lucide-react";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useId, useTransition } from "react";
import { signInAsDevRole, signOut } from "@/auth/dev-actions";
import { isRole, ROLES, type Session } from "@/auth/permissions";
import { LOCALES } from "@/i18n/locales";
import { useSetLocale } from "@/i18n/use-set-locale";

const THEMES: readonly ThemePreference[] = ["light", "dark", "system"];

interface UserMenuProps {
  session: Session;
  /** Offer the development role switcher (HV_WEB_DEV_TOOLS). */
  devTools: boolean;
}

export function UserMenu({ session, devTools }: UserMenuProps) {
  const t = useTranslations("shell.account");
  const languages = useTranslations("shell.languages");
  const roles = useTranslations("roles");
  const locale = useLocale();
  const setLocale = useSetLocale();
  const { preference, setPreference } = useTheme();
  const pathname = usePathname();
  const [, startTransition] = useTransition();
  const ids = { theme: useId(), language: useId(), role: useId() };

  function switchRole(role: string) {
    if (!isRole(role)) return;
    const form = new FormData();
    form.set("role", role);
    form.set("next", pathname);
    startTransition(async () => {
      await signInAsDevRole(form);
    });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("menu")} className="rounded-full">
          <Avatar name={session.user.name} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="flex flex-col gap-0.5 font-normal text-sm">
          <span className="font-medium text-foreground">{session.user.name}</span>
          <span>{session.user.email}</span>
          <span>{session.organization?.name ?? t("allOrganizations")}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel id={ids.theme}>{t("theme")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          aria-labelledby={ids.theme}
          value={preference}
          onValueChange={(value) => {
            const choice = THEMES.find((theme) => theme === value);
            if (choice) setPreference(choice);
          }}
        >
          {THEMES.map((theme) => (
            <DropdownMenuRadioItem key={theme} value={theme}>
              {t(theme)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel id={ids.language}>{t("language")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          aria-labelledby={ids.language}
          value={locale}
          onValueChange={setLocale}
        >
          {LOCALES.map((option) => (
            <DropdownMenuRadioItem key={option} value={option} lang={option}>
              {languages(option)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {devTools ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel id={ids.role}>{t("switchRole")}</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              aria-labelledby={ids.role}
              value={session.roles[0] ?? ""}
              onValueChange={switchRole}
            >
              {ROLES.map((role) => (
                <DropdownMenuRadioItem key={role} value={role}>
                  {roles(role)}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() =>
            startTransition(async () => {
              await signOut();
            })
          }
        >
          <LogOut aria-hidden />
          {t("signOut")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
