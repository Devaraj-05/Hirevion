import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { HOME_PATH } from "./next-path";

/** Shown in place of a page the session may not open. Every role can open the dashboard. */
export async function Forbidden() {
  const t = await getTranslations("forbidden");
  return (
    <section className="mx-auto flex max-w-lg flex-col gap-3 py-16 text-center">
      <h1 className="font-semibold text-xl">{t("title")}</h1>
      <p className="text-muted-foreground">{t("body")}</p>
      <p>
        <Link href={HOME_PATH} className="text-accent underline-offset-4 hover:underline">
          {t("back")}
        </Link>
      </p>
    </section>
  );
}
