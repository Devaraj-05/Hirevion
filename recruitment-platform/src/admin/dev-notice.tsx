import { Button, EmptyState } from "@hirevion/ui";
import { UserRoundX } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

/** Administration changes real accounts: development sessions have none, so they see this. */
export async function AdminDevNotice() {
  const t = await getTranslations("admin.common");
  return (
    <EmptyState
      icon={<UserRoundX />}
      title={t("devTitle")}
      description={t("devBody")}
      action={
        <Button asChild variant="secondary">
          <Link href="/login">{t("signIn")}</Link>
        </Button>
      }
    />
  );
}
