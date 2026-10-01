import { getTranslations } from "next-intl/server";

export default async function PortalHome() {
  const t = await getTranslations("portal");
  return (
    <main>
      <h1>{t("title")}</h1>
    </main>
  );
}
