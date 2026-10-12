import { buttonVariants } from "@hirevion/ui";
import { getTranslations } from "next-intl/server";
import { PortalHeading, portalMetadata } from "@/portal/portal-page";
import { getDownloads } from "@/portal/server";

export const generateMetadata = portalMetadata("download");

const STEPS = ["step1", "step2", "step3", "step4", "step5"] as const;

/** The desktop app (SP-07c's release registry), its system requirements and install help. */
export default async function PortalDownloadPage() {
  const t = await getTranslations("portal.download");
  const downloads = await getDownloads();
  return (
    <>
      <PortalHeading page="download" intro={t("intro")} />
      {downloads === null ? (
        <p role="alert" className="text-sm">
          {t("loadFailed")}
        </p>
      ) : (
        <div className="grid gap-8">
          <section className="grid gap-3">
            {downloads.download_url ? (
              <a
                href={downloads.download_url}
                className={buttonVariants({ className: "w-fit" })}
                rel="noopener noreferrer"
              >
                {t("button")}
              </a>
            ) : (
              <p className="rounded-md bg-surface-muted px-3 py-2 text-sm">{t("notPublished")}</p>
            )}
            {downloads.releases.length > 0 ? (
              <ul className="grid gap-1 text-muted-foreground text-sm">
                {downloads.releases.map((release) => (
                  <li key={release.arch}>
                    {t("latest", { version: release.version, arch: release.arch })}
                  </li>
                ))}
              </ul>
            ) : null}
            {downloads.minimum_version !== "0.0.0" ? (
              <p className="text-muted-foreground text-sm">
                {t("minimum", { version: downloads.minimum_version })}
              </p>
            ) : null}
          </section>
          <section aria-labelledby="requirements" className="grid gap-2">
            <h2 id="requirements" className="font-semibold text-lg">
              {t("requirementsTitle")}
            </h2>
            <ul className="grid list-disc gap-1 pl-6 text-sm">
              {downloads.system_requirements.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="install" className="grid gap-2">
            <h2 id="install" className="font-semibold text-lg">
              {t("installTitle")}
            </h2>
            <ol className="grid list-decimal gap-1 pl-6 text-sm">
              {STEPS.map((step) => (
                <li key={step}>{t(`install.${step}`)}</li>
              ))}
            </ol>
          </section>
          <section aria-labelledby="help" className="grid gap-2">
            <h2 id="help" className="font-semibold text-lg">
              {t("helpTitle")}
            </h2>
            <p className="text-sm">{t("help")}</p>
          </section>
        </div>
      )}
    </>
  );
}
