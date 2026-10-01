import { cn } from "@hirevion/ui";
import Link from "next/link";

export interface SectionTab {
  href: string;
  label: string;
  active: boolean;
}

/** A section's tabs. They navigate (each is a URL), so they're links, not an ARIA tab list. */
export function SectionTabs({ label, tabs }: { label: string; tabs: readonly SectionTab[] }) {
  return (
    <nav aria-label={label} className="mb-6 border-border border-b">
      <ul className="-mb-px flex gap-5 overflow-x-auto">
        {tabs.map((tab) => (
          <li key={tab.href}>
            <Link
              href={tab.href}
              aria-current={tab.active ? "page" : undefined}
              className={cn(
                "inline-flex h-10 items-center whitespace-nowrap border-b-2 px-1 font-medium text-sm",
                tab.active
                  ? "border-accent text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
