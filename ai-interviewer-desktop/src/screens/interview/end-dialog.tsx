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
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEnd: () => void;
}) {
  const t = useTranslations("interview.endDialog");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={t("title")}
        description={t("body")}
        closeLabel={t("continue")}
        className="rounded-[20px]"
        footer={
          <>
            {/* The safe choice takes the focus. */}
            <PillButton variant="secondary" autoFocus onClick={() => onOpenChange(false)}>
              {t("continue")}
            </PillButton>
            <PillButton variant="danger" onClick={onEnd}>
              {t("end")}
            </PillButton>
          </>
        }
      />
    </Dialog>
  );
}
