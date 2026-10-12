import { getTranslations } from "next-intl/server";
import { PortalForgotForm } from "@/portal/forms";
import { PortalCard, portalMetadata } from "@/portal/portal-page";

export const generateMetadata = portalMetadata("forgotPassword");

export default async function PortalForgotPasswordPage() {
  const pages = await getTranslations("portal.pages");
  const t = await getTranslations("portal.forgot");
  return (
    <PortalCard>
      <h1 className="font-semibold text-xl">{pages("forgotPassword")}</h1>
      <p className="text-muted-foreground text-sm">{t("intro")}</p>
      <PortalForgotForm />
    </PortalCard>
  );
}
