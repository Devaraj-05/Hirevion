import { EmptyState } from "@hirevion/ui";
import { CalendarClock } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { InterviewCard } from "@/portal/interview-card";
import { PortalHeading, portalMetadata } from "@/portal/portal-page";
import { getPortalInterviews, requirePortalSession } from "@/portal/server";

export const generateMetadata = portalMetadata("status");

/** The candidate's interviews, their windows and countdowns (master plan §6.3). */
export default async function PortalHomePage() {
  await requirePortalSession();
  const t = await getTranslations("portal.interviews");
  const list = await getPortalInterviews();
  return (
    <>
      <PortalHeading page="status" intro={t("intro")} />
      {list === null ? (
        <p role="alert" className="text-sm">
          {t("loadFailed")}
        </p>
      ) : list.interviews.length === 0 ? (
        <EmptyState icon={<CalendarClock />} title={t("empty")} description={t("emptyHint")} />
      ) : (
        <ul className="grid gap-4">
          {list.interviews.map((interview) => (
            <li key={interview.id}>
              <InterviewCard interview={interview} serverNow={list.now} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
