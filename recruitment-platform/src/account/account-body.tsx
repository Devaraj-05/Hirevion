import { Button, Card, CardContent, CardHeader, CardTitle, EmptyState } from "@hirevion/ui";
import { UserRoundX } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { PageBodyProps } from "@/page/bodies";
import { LanguageSwitcher } from "@/shell/language-switcher";
import { EmailCard } from "./email-card";
import { PasswordCard } from "./password-card";
import { SessionsCard } from "./sessions-card";

/** The signed-in user's own account: profile, password, email and devices. */
export async function AccountBody({ session }: PageBodyProps) {
  const t = await getTranslations("account");
  if (session.source === "dev") {
    return (
      <EmptyState
        icon={<UserRoundX />}
        title={t("dev.title")}
        description={t("dev.body")}
        action={
          <Button asChild variant="secondary">
            <Link href="/login">{t("dev.signIn")}</Link>
          </Button>
        }
      />
    );
  }
  const roles = await getTranslations("roles");
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("profile.title")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid gap-3 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-muted-foreground">{t("profile.name")}</dt>
            <dd>{session.user.name}</dd>
            <dt className="text-muted-foreground">{t("profile.email")}</dt>
            <dd>{session.user.email}</dd>
            <dt className="text-muted-foreground">{t("profile.organization")}</dt>
            <dd>{session.organization?.name ?? t("profile.allOrganizations")}</dd>
            <dt className="text-muted-foreground">{t("profile.roles")}</dt>
            <dd>
              {[
                ...session.roles.map((role) =>
                  roles.has(role as "recruiter") ? roles(role as "recruiter") : role,
                ),
                ...session.customRoles,
              ].join(", ")}
            </dd>
          </dl>
          <p className="text-muted-foreground text-sm">{t("profile.nameNote")}</p>
          <div className="flex items-center gap-3">
            <span className="text-sm">{t("profile.language")}</span>
            <LanguageSwitcher />
          </div>
        </CardContent>
      </Card>
      <PasswordCard email={session.user.email} />
      <EmailCard email={session.user.email} />
      <SessionsCard />
    </div>
  );
}
