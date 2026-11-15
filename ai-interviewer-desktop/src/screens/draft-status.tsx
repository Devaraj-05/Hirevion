import { useFormatter, useTranslations } from "use-intl";
import type { SaveStatus } from "../interview/coding";

/** Where a workspace's draft stands ("Saved at 10:02:03"): the coding console and the notes pad
 * both save drafts the same way (`DraftSaver`). */
export function DraftStatus({ id, status }: { id: string; status: SaveStatus }) {
  const t = useTranslations("drafts");
  const format = useFormatter();
  return (
    <p id={id} role="status" className="text-muted-foreground text-sm">
      {status.kind === "saved"
        ? t("saved", {
            time: format.dateTime(new Date(status.at), {
              hour: "numeric",
              minute: "2-digit",
              second: "2-digit",
            }),
          })
        : t(status.kind)}
    </p>
  );
}
