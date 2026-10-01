import { Button } from "@hirevion/ui";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { signInAsDevRole } from "@/auth/dev-actions";
import { safeNext } from "@/auth/next-path";
import { ROLES } from "@/auth/permissions";
import { devToolsEnabled } from "@/config/environment";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("login");
  return { title: t("title") };
}

interface LoginPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

// Until SP-02 brings real sign-in, development builds offer one fixture session per role.
export default async function LoginPage({ searchParams }: LoginPageProps) {
  const t = await getTranslations("login");
  const roles = await getTranslations("roles");
  const { next } = await searchParams;
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-6 px-6">
      <h1 className="font-semibold text-xl">{t("title")}</h1>
      {devToolsEnabled() ? (
        <form action={signInAsDevRole} className="flex flex-col gap-3">
          <p className="text-muted-foreground">{t("devIntro")}</p>
          <input
            type="hidden"
            name="next"
            value={safeNext(typeof next === "string" ? next : null)}
          />
          {ROLES.map((role) => (
            <Button key={role} type="submit" name="role" value={role} variant="secondary">
              {t("continueAs", { role: roles(role) })}
            </Button>
          ))}
        </form>
      ) : (
        <p className="text-muted-foreground">{t("unavailable")}</p>
      )}
    </main>
  );
}
