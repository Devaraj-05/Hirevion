import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { LanguageSwitcher } from "@/shell/language-switcher";

/** Sign-in and the emailed-link pages: the brand, the language menu and one card. */
export default async function AuthLayout({ children }: { children: ReactNode }) {
  const app = await getTranslations("app");
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex items-center justify-between px-6 py-4">
        <span className="font-semibold">{app("name")}</span>
        <LanguageSwitcher />
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pt-[8vh] pb-16">
        <div className="flex w-full max-w-sm flex-col gap-6 rounded-lg border border-border bg-surface p-6 shadow-sm">
          {children}
        </div>
      </main>
    </div>
  );
}
