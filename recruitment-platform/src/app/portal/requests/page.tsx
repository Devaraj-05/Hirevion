import { Badge, type BadgeTone } from "@hirevion/ui";
import { getFormatter, getTranslations } from "next-intl/server";
import { PortalHeading, portalMetadata } from "@/portal/portal-page";
import { RequestsPanel } from "@/portal/requests-panel";
import { getPortalInterviews, getPortalRequests, requirePortalSession } from "@/portal/server";

export const generateMetadata = portalMetadata("requests");

const TONES: Record<string, BadgeTone> = {
  open: "info",
  in_progress: "warning",
  resolved: "success",
  declined: "neutral",
};

interface RequestsPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

/** Master plan §6.3's requests: reschedule, support, adjustments or an alternative process,
 * the data rights and consent withdrawal, with the organisation's replies. */
export default async function PortalRequestsPage({ searchParams }: RequestsPageProps) {
  await requirePortalSession();
  const t = await getTranslations("portal.requests");
  const format = await getFormatter();
  const params = await searchParams;
  const [interviews, requests] = await Promise.all([getPortalInterviews(), getPortalRequests()]);
  const choices = (interviews?.interviews ?? []).map((item) => ({
    id: item.id,
    label: `${item.job_title} (${item.reference})`,
  }));
  return (
    <>
      <PortalHeading page="requests" intro={t("intro")} />
      <div className="grid gap-10">
        <section aria-labelledby="new-request" className="grid gap-3">
          <h2 id="new-request" className="font-semibold text-lg">
            {t("newTitle")}
          </h2>
          <RequestsPanel
            interviews={choices}
            initialKind={typeof params.kind === "string" ? params.kind : null}
            initialInterview={typeof params.interview === "string" ? params.interview : null}
          />
        </section>
        <section aria-labelledby="my-requests" className="grid gap-3">
          <h2 id="my-requests" className="font-semibold text-lg">
            {t("mine")}
          </h2>
          {requests === null ? (
            <p role="alert" className="text-sm">
              {t("loadFailed")}
            </p>
          ) : requests.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("empty")}</p>
          ) : (
            <ul className="grid gap-3">
              {requests.map((request) => (
                <li
                  key={request.id}
                  className="grid gap-2 rounded-lg border border-border bg-surface p-4 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-medium">{t(`kinds.${request.kind}`)}</h3>
                    <Badge tone={TONES[request.status] ?? "neutral"}>
                      {t(`status.${request.status}`)}
                    </Badge>
                  </div>
                  <p className="text-muted-foreground text-xs">
                    {[
                      request.reference,
                      t("sentOn", {
                        date: format.dateTime(new Date(request.created_at), {
                          dateStyle: "medium",
                        }),
                      }),
                    ].join(" · ")}
                  </p>
                  {request.message ? (
                    <p className="whitespace-pre-wrap">{request.message}</p>
                  ) : null}
                  {request.response ? (
                    <div className="rounded-md bg-surface-muted px-3 py-2">
                      <p className="font-medium">{t("reply")}</p>
                      <p className="whitespace-pre-wrap">{request.response}</p>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
