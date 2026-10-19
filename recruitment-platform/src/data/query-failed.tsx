"use client";

import { Button } from "@hirevion/ui";
import { useTranslations } from "next-intl";

/** What a list or panel shows when its data could not be loaded: a failed load must never look
 * like "nothing here". */
export function QueryFailed({ onRetry }: { onRetry?: () => void }) {
  const t = useTranslations("data");
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 text-danger text-sm">
      <span>{t("loadFailed")}</span>
      {onRetry ? (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          {t("retry")}
        </Button>
      ) : null}
    </div>
  );
}
