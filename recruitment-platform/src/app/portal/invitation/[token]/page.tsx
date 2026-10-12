import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { PortalPasswordForm } from "@/portal/forms";
import { PortalCard, portalMetadata } from "@/portal/portal-page";

export const generateMetadata = portalMetadata("invitation");

/** The invitation email's link (PRD §25): the candidate sets their first password here, which
 * also confirms their email address. */
export default async function PortalInvitationPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const pages = await getTranslations("portal.pages");
  const t = await getTranslations("portal.password");
  const nav = await getTranslations("portal.nav");
  return (
    <PortalCard>
      <h1 className="font-semibold text-xl">{pages("invitation")}</h1>
      <p className="text-muted-foreground text-sm">{t("setIntro")}</p>
      <PortalPasswordForm mode="set" token={token} />
      <Link href="/notices" className="text-primary text-sm underline">
        {nav("notices")}
      </Link>
    </PortalCard>
  );
}
