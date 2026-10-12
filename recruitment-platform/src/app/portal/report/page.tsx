import { getTranslations } from "next-intl/server";
import { PortalHeading, portalMetadata } from "@/portal/portal-page";
import { requirePortalSession } from "@/portal/server";

export const generateMetadata = portalMetadata("report");

const ITEMS = ["completion", "general", "technical", "coding", "nextStep"] as const;

/** PRD §99: what the organisation chooses to share. The shared report itself arrives with
 * SP-17; until then this says what it may hold. */
export default async function PortalReportPage() {
  await requirePortalSession();
  const t = await getTranslations("portal.reportPage");
  return (
    <>
      <PortalHeading page="report" intro={t("intro")} />
      <section aria-labelledby="may-share" className="grid gap-2">
        <h2 id="may-share" className="font-semibold text-lg">
          {t("mayShare")}
        </h2>
        <ul className="grid list-disc gap-1 pl-6 text-sm">
          {ITEMS.map((item) => (
            <li key={item}>{t(`items.${item}`)}</li>
          ))}
        </ul>
        <p className="mt-4 rounded-md bg-surface-muted px-3 py-2 text-sm">{t("notYet")}</p>
      </section>
    </>
  );
}
