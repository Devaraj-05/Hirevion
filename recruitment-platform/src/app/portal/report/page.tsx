import { EmptyState } from "@hirevion/ui";
import { FileText } from "lucide-react";
import { getFormatter, getTranslations } from "next-intl/server";
import { PortalHeading, portalMetadata } from "@/portal/portal-page";
import { getPortalReports, requirePortalSession } from "@/portal/server";

export const generateMetadata = portalMetadata("report");

const ITEMS = ["completion", "general", "technical", "coding", "nextStep"] as const;

/** PRD §99: what the organisation chose to share and a recruiter released, as it read when it
 * was released. Internal reports never reach this page; with nothing released it says what may
 * be shared. */
export default async function PortalReportPage() {
  await requirePortalSession();
  const t = await getTranslations("portal.reportPage");
  const format = await getFormatter();
  const list = await getPortalReports();
  return (
    <>
      <PortalHeading page="report" intro={t("intro")} />
      {list === null ? (
        <p role="alert" className="text-sm">
          {t("loadFailed")}
        </p>
      ) : list.reports.length === 0 ? (
        <section aria-labelledby="may-share" className="grid gap-2">
          <h2 id="may-share" className="font-semibold text-lg">
            {t("mayShare")}
          </h2>
          <ul className="grid list-disc gap-1 pl-6 text-sm">
            {ITEMS.map((item) => (
              <li key={item}>{t(`items.${item}`)}</li>
            ))}
          </ul>
          <EmptyState
            className="mt-4"
            icon={<FileText />}
            title={t("notYet")}
            description={t("notYetHint")}
          />
        </section>
      ) : (
        <ul className="grid gap-6">
          {list.reports.map((report) => (
            <li key={report.interview_id}>
              <article aria-labelledby={`report-${report.interview_id}`} className="grid gap-3">
                <header className="grid gap-0.5">
                  <h2 id={`report-${report.interview_id}`} className="font-semibold text-lg">
                    {t("reportTitle", { job: report.job_title, reference: report.reference })}
                  </h2>
                  {report.released_at ? (
                    <p className="text-muted-foreground text-sm">
                      {t("released", {
                        when: format.dateTime(new Date(report.released_at), { dateStyle: "long" }),
                      })}
                    </p>
                  ) : null}
                </header>
                <dl className="grid gap-3">
                  {report.items.map((item) => (
                    <div
                      key={item.key}
                      className="grid gap-0.5 rounded-lg border border-border p-4"
                    >
                      <dt className="font-medium text-sm">{item.title}</dt>
                      <dd className="whitespace-pre-wrap break-words text-sm">{item.text}</dd>
                    </div>
                  ))}
                </dl>
                <p>
                  <a
                    href={`/api/v1/portal/report/${report.interview_id}/pdf`}
                    className="text-sm underline"
                  >
                    {t("download", { reference: report.reference })}
                  </a>
                </p>
              </article>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
