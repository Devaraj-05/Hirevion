import { getTranslations } from "next-intl/server";

export default async function PortalHome() {
  const t = await getTranslations("portal");
  return <h1 className="font-semibold text-xl">{t("title")}</h1>;
}
