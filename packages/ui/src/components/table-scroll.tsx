import type { ReactNode } from "react";
import { cn } from "../lib/cn";

/**
 * Holds a table that may scroll sideways in a narrow layout. The scroller is named after its
 * table and can be reached and scrolled with the keyboard (WCAG 2.1.1, axe
 * "scrollable-region-focusable"). It is a group, not a landmark, so a page with many tables
 * doesn't fill the landmark list or need a unique name for each.
 */
export function TableScroll({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    // biome-ignore lint/a11y/useSemanticElements: <fieldset> groups form controls; this groups a scrolling table.
    <div
      role="group"
      aria-label={label}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a table that scrolls sideways must be reachable by keyboard.
      tabIndex={0}
      className={cn("overflow-x-auto", className)}
    >
      {children}
    </div>
  );
}
