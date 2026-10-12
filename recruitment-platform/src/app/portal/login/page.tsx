import { getTranslations } from "next-intl/server";
import { PortalLoginForm } from "@/portal/forms";
import { safePortalNext } from "@/portal/paths";
import { PortalCard, portalMetadata } from "@/portal/portal-page";

export const generateMetadata = portalMetadata("login");

interface LoginPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function PortalLoginPage({ searchParams }: LoginPageProps) {
  const pages = await getTranslations("portal.pages");
  const t = await getTranslations("portal.login");
  const params = await searchParams;
  const next = safePortalNext(typeof params.next === "string" ? params.next : null);
  const notice = params.set === "1" ? t("setDone") : params.reset === "1" ? t("resetDone") : null;
  return (
    <PortalCard>
      <h1 className="font-semibold text-xl">{pages("login")}</h1>
      <p className="text-muted-foreground text-sm">{t("intro")}</p>
      {notice ? (
        <p role="status" className="rounded-md bg-success-subtle px-3 py-2 text-sm">
          {notice}
        </p>
      ) : null}
      <PortalLoginForm next={next} />
      <p className="text-muted-foreground text-sm">{t("noPassword")}</p>
    </PortalCard>
  );
}
