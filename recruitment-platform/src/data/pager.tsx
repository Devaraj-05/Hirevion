"use client";

import { Button } from "@hirevion/ui";
import { useTranslations } from "next-intl";

interface PagerProps {
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}

/** Previous and next for a cursor-paginated list (`useCursorPage`). */
export function Pager({ hasPrevious, hasNext, onPrevious, onNext }: PagerProps) {
  const t = useTranslations("table");
  if (!hasPrevious && !hasNext) return null;
  return (
    <nav aria-label={t("pager")} className="flex justify-end gap-2">
      <Button variant="secondary" size="sm" disabled={!hasPrevious} onClick={onPrevious}>
        {t("previous")}
      </Button>
      <Button variant="secondary" size="sm" disabled={!hasNext} onClick={onNext}>
        {t("next")}
      </Button>
    </nav>
  );
}
