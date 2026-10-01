import { getTranslations } from "next-intl/server";

export default async function DashboardPage() {
  const t = await getTranslations("dashboard");
  return (
    <main>
      <h1>{t("title")}</h1>
    </main>
  );
}
