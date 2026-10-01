import type { ReactNode } from "react";
import { ShellFrame } from "@/shell/shell-frame";

// The refusal keeps the app's navigation, so it isn't a dead end. Only signed-in sessions are
// sent here (the proxy redirects anonymous visitors to sign in first).
export default function ForbiddenLayout({ children }: { children: ReactNode }) {
  return <ShellFrame>{children}</ShellFrame>;
}
