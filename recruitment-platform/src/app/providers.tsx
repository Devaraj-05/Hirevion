"use client";

import { Toaster, TooltipProvider, useTheme } from "@hirevion/ui";
import type { ReactNode } from "react";
import { QueryProvider } from "@/data/query-provider";

/** Client-side context every page shares. */
export function Providers({ children }: { children: ReactNode }) {
  const { preference } = useTheme();
  return (
    <QueryProvider>
      <TooltipProvider delayDuration={300}>
        {children}
        <Toaster theme={preference} />
      </TooltipProvider>
    </QueryProvider>
  );
}
