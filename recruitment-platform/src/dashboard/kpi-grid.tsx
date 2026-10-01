"use client";

import { KpiTile } from "@hirevion/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useId } from "react";
import { KPIS, type Kpi } from "./model";

/** The PRD §10 figures; a figure whose module hasn't landed shows "no data yet". */
export function KpiGrid({ values }: { values: Partial<Record<Kpi, number>> }) {
  const t = useTranslations("dashboard.kpis");
  const format = useFormatter();
  const headingId = useId();
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        {t("title")}
      </h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {KPIS.map((kpi) => {
          const value = values[kpi];
          return (
            <KpiTile
              key={kpi}
              label={t(kpi)}
              value={value === undefined ? null : format.number(value)}
              noDataLabel={t("noData")}
            />
          );
        })}
      </div>
    </section>
  );
}
