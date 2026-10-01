"use client";

import type { DataTableLabels } from "@hirevion/ui";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

/** The DataTable's strings in the current language. Pass a stable (module-level) `rowName`. */
export function useTableLabels<T>(rowName: (row: T) => string): DataTableLabels<T> {
  const t = useTranslations("table");
  return useMemo(
    () => ({
      selectAll: t("selectAll"),
      selectRow: (row: T) => t("selectRow", { name: rowName(row) }),
      selected: (count: number) => t("selected", { count }),
      clearSelection: t("clearSelection"),
      columns: t("columns"),
      views: t("views"),
      viewName: t("viewName"),
      saveView: t("saveView"),
      applyView: (name: string) => t("applyView", { name }),
      deleteView: (name: string) => t("deleteView", { name }),
      noViews: t("noViews"),
    }),
    [t, rowName],
  );
}
