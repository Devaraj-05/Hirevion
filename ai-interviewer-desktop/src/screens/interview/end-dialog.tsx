import { Dialog, DialogContent } from "@hirevion/ui";
import { useTranslations } from "use-intl";
import { PillButton } from "../../ui/kit";

/**
 * End interview, confirmed (C8-12; one attempt, C8-9): the screen's only destructive action,
 * and the same question when the window is closed. Continue is the safe default.
 */
export function EndDialog({
  open,
  onOpenChange,
  onEnd,
  ending = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEnd: () => void;
  /** The candidate's End is under way: both choices wait, and End says so. An interview that
   * ends by itself never opens this dialog. */
  ending?: boolean;
}) {
  const t = useTranslations("interview.endDialog");
  return (
    <Dialog open={open} onOpenChange={(next) => !ending && onOpenChange(next)}>
      <DialogContent
        title={t("title")}
        description={t("body")}
        closeLabel={t("continue")}
        className="rounded-[20px]"
        footer={
          <>
            {/* The safe choice takes the focus. */}
            <PillButton
              variant="secondary"
              autoFocus
              disabled={ending}
              onClick={() => onOpenChange(false)}
            >
              {t("continue")}
            </PillButton>
            <PillButton variant="danger" disabled={ending} aria-busy={ending} onClick={onEnd}>
              {ending ? t("ending") : t("end")}
            </PillButton>
          </>
        }
      />
    </Dialog>
  );
}
