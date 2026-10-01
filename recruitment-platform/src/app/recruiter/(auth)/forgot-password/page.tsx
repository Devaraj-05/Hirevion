import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { ForgotPasswordForm } from "@/auth/forms/forgot-password-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("auth.forgot");
  return { title: t("title") };
}

export default async function ForgotPasswordPage() {
  const t = await getTranslations("auth.forgot");
  return (
    <>
      <h1 className="font-semibold text-xl">{t("title")}</h1>
      <p className="text-muted-foreground text-sm">{t("intro")}</p>
      <ForgotPasswordForm />
      <Link href="/login" className="text-accent text-sm hover:underline">
        {t("back")}
      </Link>
    </>
  );
}
