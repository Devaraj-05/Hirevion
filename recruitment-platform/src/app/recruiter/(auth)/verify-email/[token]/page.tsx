import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { VerifyEmail } from "@/auth/forms/verify-email";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("auth.verify");
  return { title: t("title"), robots: { index: false, follow: false } };
}

export default async function VerifyEmailPage({ params }: { params: Promise<{ token: string }> }) {
  const t = await getTranslations("auth.verify");
  const { token } = await params;
  return (
    <>
      <h1 className="font-semibold text-xl">{t("title")}</h1>
      <VerifyEmail token={token} />
    </>
  );
}
