import type { ReactNode } from "react";
import { requireSession } from "@/auth/server";

export default async function ShellLayout({ children }: { children: ReactNode }) {
  await requireSession();
  return <main id="main">{children}</main>;
}
