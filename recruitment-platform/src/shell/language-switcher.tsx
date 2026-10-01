"use client";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@hirevion/ui";
import { Languages } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { LOCALES } from "@/i18n/locales";
import { useSetLocale } from "@/i18n/use-set-locale";

/** The language menu for pages without the user menu (the candidate portal, sign-in). */
export function LanguageSwitcher() {
  const t = useTranslations("shell");
  const languages = useTranslations("shell.languages");
  const locale = useLocale();
  const setLocale = useSetLocale();
  const current = languages(locale);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={t("languageMenu", { language: current })}>
          <Languages aria-hidden />
          {current}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={locale} onValueChange={setLocale}>
          {LOCALES.map((option) => (
            <DropdownMenuRadioItem key={option} value={option} lang={option}>
              {languages(option)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
