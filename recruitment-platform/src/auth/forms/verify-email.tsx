"use client";

import { Button } from "@hirevion/ui";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { verifyEmail } from "@/auth/api";

/**
 * Confirms a new email address. It waits for a click rather than confirming on load, so mail
 * scanners that open links can't use the single-use token.
 */
export function VerifyEmail({ token }: { token: string }) {
  const t = useTranslations("auth.verify");
  const [outcome, setOutcome] = useState<"verified" | "expired" | "unavailable" | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    setOutcome(await verifyEmail(token));
    setBusy(false);
  }

  if (outcome === "verified") {
    return (
      <div className="flex flex-col gap-4">
        <p role="status" className="rounded-md bg-success-subtle px-3 py-2 text-sm">
          {t("verified")}
        </p>
        <Link href="/dashboard" className="text-accent text-sm hover:underline">
          {t("continue")}
        </Link>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">{t("intro")}</p>
      {outcome ? (
        <p
          role="alert"
          className="rounded-md border border-danger bg-danger-subtle px-3 py-2 text-danger text-sm"
        >
          {outcome === "expired" ? t("expired") : t("unavailable")}
        </p>
      ) : null}
      <Button onClick={confirm} disabled={busy}>
        {t("submit")}
      </Button>
    </div>
  );
}
