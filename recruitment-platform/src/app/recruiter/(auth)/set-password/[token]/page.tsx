import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { NewPasswordForm } from "@/auth/forms/new-password-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("auth.newPassword");
  return { title: t("setTitle"), robots: { index: false, follow: false } };
}

/** An invited user's first password (the link from `hv create-super-admin`, later invitations). */
export default async function SetPasswordPage({ params }: { params: Promise<{ token: string }> }) {
  const t = await getTranslations("auth.newPassword");
  const { token } = await params;
  return (
    <>
      <h1 className="font-semibold text-xl">{t("setTitle")}</h1>
      <p className="text-muted-foreground text-sm">{t("setIntro")}</p>
      <NewPasswordForm token={token} mode="set" />
    </>
  );
}
