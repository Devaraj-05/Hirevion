import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { requireSession } from "@/auth/server";
import { devToolsEnabled } from "@/config/environment";
import { AppShell } from "@/shell/app-shell";
import { SIDEBAR_COOKIE } from "@/shell/preferences";

export default async function ShellLayout({ children }: { children: ReactNode }) {
  const session = await requireSession();
  const collapsed = (await cookies()).get(SIDEBAR_COOKIE)?.value === "collapsed";
  return (
    <AppShell session={session} devTools={devToolsEnabled()} initialCollapsed={collapsed}>
      {children}
    </AppShell>
  );
}
