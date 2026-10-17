import { getTranslations } from "next-intl/server";
import { isDisclosure } from "@/portal/disclosures";
import { Markdown } from "@/portal/markdown";
import { PortalHeading, portalMetadata } from "@/portal/portal-page";
import { getNotices, getPortalSession } from "@/portal/server";

export const generateMetadata = portalMetadata("notices");

/** PRD §83: the ten kinds of data an interview may collect, and the six policies. Public, as the
 * invitation links here before the candidate has a password. */
export default async function PortalNoticesPage() {
  const t = await getTranslations("portal.noticesPage");
  const [notices, session] = await Promise.all([getNotices(), getPortalSession()]);
  return (
    <>
      <PortalHeading page="notices" intro={t("intro")} />
      {notices === null ? (
        <p role="alert" className="text-sm">
          {t("loadFailed")}
        </p>
      ) : (
        <div className="grid gap-10">
          <section aria-labelledby="collected" className="grid gap-2">
            <h2 id="collected" className="font-semibold text-lg">
              {t("collectedTitle")}
            </h2>
            <ul className="grid list-disc gap-1 pl-6 text-sm">
              {notices.disclosures.filter(isDisclosure).map((item) => (
                <li key={item}>{t(`disclosures.${item}`)}</li>
              ))}
            </ul>
          </section>
          <nav aria-labelledby="contents" className="grid gap-2">
            <h2 id="contents" className="font-semibold text-lg">
              {t("policiesTitle")}
            </h2>
            <ul className="grid gap-1 text-sm">
              {notices.policies.map((policy) => (
                <li key={policy.key}>
                  <a
                    href={`#policy-${policy.key}`}
                    className="inline-flex min-h-6 items-center text-primary underline"
                  >
                    {policy.title}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          {notices.policies.map((policy) => (
            <section
              key={policy.key}
              id={`policy-${policy.key}`}
              aria-labelledby={`policy-${policy.key}-title`}
              className="grid scroll-mt-4 gap-3 border-border border-t pt-6"
            >
              <h2 id={`policy-${policy.key}-title`} className="font-semibold text-lg">
                {policy.title}
              </h2>
              <Markdown source={policy.body} idPrefix={policy.key} />
            </section>
          ))}
          {session ? (
            <p className="text-sm">{t("support", { email: session.organization.support_email })}</p>
          ) : null}
        </div>
      )}
    </>
  );
}
