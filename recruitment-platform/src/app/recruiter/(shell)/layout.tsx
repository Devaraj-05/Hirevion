import type { ReactNode } from "react";
import { StepUpProvider } from "@/admin/step-up";
import { ShellFrame } from "@/shell/shell-frame";

export default function ShellLayout({ children }: { children: ReactNode }) {
  return (
    <ShellFrame>
      <StepUpProvider>{children}</StepUpProvider>
    </ShellFrame>
  );
}
