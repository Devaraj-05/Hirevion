import { Button } from "@hirevion/ui";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { signInAsDevRole } from "@/auth/dev-actions";
import { LoginForm } from "@/auth/forms/login-form";
import { safeNext } from "@/auth/next-path";
import { ROLES } from "@/auth/permissions";
import { devToolsEnabled } from "@/config/environment";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("auth.login");
  return { title: t("title") };
}

interface LoginPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const t = await getTranslations("auth.login");
  const roles = await getTranslations("roles");
  const params = await searchParams;
  const next = safeNext(typeof params.next === "string" ? params.next : null);
  const notice = params.reset === "1" ? t("resetDone") : params.set === "1" ? t("setDone") : null;

  return (
    <>
      <h1 className="font-semibold text-xl">{t("title")}</h1>
      {notice ? (
        <p role="status" className="rounded-md bg-success-subtle px-3 py-2 text-sm">
          {notice}
        </p>
      ) : null}
      <LoginForm next={next} />
      {devToolsEnabled() ? (
        <section
          aria-labelledby="dev-sign-in"
          className="flex flex-col gap-3 border-border border-t pt-4"
        >
          <h2 id="dev-sign-in" className="font-medium text-sm">
            {t("devTitle")}
          </h2>
          <p className="text-muted-foreground text-sm">{t("devIntro")}</p>
          <form action={signInAsDevRole} className="flex flex-col gap-2">
            <input type="hidden" name="next" value={next} />
            {ROLES.map((role) => (
              <Button
                key={role}
                type="submit"
                name="role"
                value={role}
                variant="secondary"
                size="sm"
              >
                {t("continueAs", { role: roles(role) })}
              </Button>
            ))}
          </form>
        </section>
      ) : null}
    </>
  );
}
