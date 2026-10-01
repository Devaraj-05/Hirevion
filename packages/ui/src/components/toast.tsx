"use client";

import { Toaster as SonnerToaster, toast } from "sonner";

export { toast };

/** Toasts for transient feedback; anything important also appears in the page itself. */
export function Toaster({ theme }: { theme: "light" | "dark" | "system" }) {
  return (
    <SonnerToaster
      theme={theme}
      position="bottom-right"
      closeButton
      toastOptions={{
        classNames: {
          toast: "border border-border bg-surface text-foreground shadow-md",
          description: "text-muted-foreground",
        },
      }}
    />
  );
}
