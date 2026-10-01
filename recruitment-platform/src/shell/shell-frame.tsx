import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { requireSession } from "@/auth/server";
import { devToolsEnabled } from "@/config/environment";
import { AppShell } from "./app-shell";
import { SIDEBAR_COOKIE } from "./preferences";

/** The signed-in frame: the session's navigation around the page. */
export async function ShellFrame({ children }: { children: ReactNode }) {
  const session = await requireSession();
  const collapsed = (await cookies()).get(SIDEBAR_COOKIE)?.value === "collapsed";
  return (
    <AppShell session={session} devTools={devToolsEnabled()} initialCollapsed={collapsed}>
      {children}
    </AppShell>
  );
}
