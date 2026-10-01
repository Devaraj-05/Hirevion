"use client";

import { Toaster, TooltipProvider, useTheme } from "@hirevion/ui";
import type { ReactNode } from "react";

/** Client-side context every page shares. */
export function Providers({ children }: { children: ReactNode }) {
  const { preference } = useTheme();
  return (
    <TooltipProvider delayDuration={300}>
      {children}
      <Toaster theme={preference} />
    </TooltipProvider>
  );
}
