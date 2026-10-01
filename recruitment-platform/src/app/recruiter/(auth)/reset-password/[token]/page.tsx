import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { NewPasswordForm } from "@/auth/forms/new-password-form";

// The token is in the URL: keep the page out of search indexes (the Referrer-Policy already
// keeps it from other sites).
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("auth.newPassword");
  return { title: t("resetTitle"), robots: { index: false, follow: false } };
}

export default async function ResetPasswordPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const t = await getTranslations("auth.newPassword");
  const { token } = await params;
  return (
    <>
      <h1 className="font-semibold text-xl">{t("resetTitle")}</h1>
      <NewPasswordForm token={token} mode="reset" />
    </>
  );
}
