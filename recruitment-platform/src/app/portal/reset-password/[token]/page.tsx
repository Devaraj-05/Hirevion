import { getTranslations } from "next-intl/server";
import { PortalPasswordForm } from "@/portal/forms";
import { PortalCard, portalMetadata } from "@/portal/portal-page";

export const generateMetadata = portalMetadata("resetPassword");

export default async function PortalResetPasswordPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const pages = await getTranslations("portal.pages");
  const t = await getTranslations("portal.password");
  return (
    <PortalCard>
      <h1 className="font-semibold text-xl">{pages("resetPassword")}</h1>
      <p className="text-muted-foreground text-sm">{t("resetIntro")}</p>
      <PortalPasswordForm mode="reset" token={token} />
    </PortalCard>
  );
}
