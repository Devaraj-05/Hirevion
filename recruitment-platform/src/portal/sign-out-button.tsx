"use client";

import { Button } from "@hirevion/ui";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { portalSignOut } from "./api";

export function SignOutButton() {
  const t = useTranslations("portal.nav");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        await portalSignOut();
        router.replace("/login");
        router.refresh();
      }}
    >
      {t("signOut")}
    </Button>
  );
}
