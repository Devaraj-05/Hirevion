"use client";

import {
  Button,
  DialogClose,
  EmptyState,
  IconButton,
  Sheet,
  SheetContent,
  SheetTrigger,
} from "@hirevion/ui";
import { Bell, BellOff } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { can, type Session } from "@/auth/permissions";

/** The notification centre's panel. Empty until SP-18 delivers notifications. */
export function NotificationsButton({ session }: { session: Session }) {
  const t = useTranslations("shell.notifications");
  const footer = can(session, "notifications.view") ? (
    <DialogClose asChild>
      <Button asChild variant="secondary">
        <Link href="/notifications">{t("seeAll")}</Link>
      </Button>
    </DialogClose>
  ) : undefined;
  return (
    <Sheet>
      <SheetTrigger asChild>
        <IconButton label={t("open")} icon={<Bell aria-hidden />} />
      </SheetTrigger>
      <SheetContent title={t("title")} closeLabel={t("close")} {...(footer ? { footer } : {})}>
        <EmptyState level={3} icon={<BellOff />} title={t("empty")} description={t("emptyHint")} />
      </SheetContent>
    </Sheet>
  );
}
