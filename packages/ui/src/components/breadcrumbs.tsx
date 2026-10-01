import { ChevronRight } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

export interface Crumb {
  label: string;
  href: string;
}

export interface BreadcrumbsProps {
  /** The navigation landmark's name, e.g. "Breadcrumb". */
  label: string;
  items: readonly Crumb[];
  /** The link component to use (e.g. Next's `Link`); defaults to <a>. */
  linkComponent?: ComponentType<{ href: string; className?: string; children: ReactNode }>;
}

export function Breadcrumbs({ label, items, linkComponent: LinkComponent }: BreadcrumbsProps) {
  return (
    <nav aria-label={label}>
      <ol className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={item.href} className="flex items-center gap-1">
              {last ? (
                <span aria-current="page" className="font-medium text-foreground">
                  {item.label}
                </span>
              ) : LinkComponent ? (
                <LinkComponent href={item.href} className="hover:text-foreground">
                  {item.label}
                </LinkComponent>
              ) : (
                <a href={item.href} className="hover:text-foreground">
                  {item.label}
                </a>
              )}
              {last ? null : <ChevronRight className="size-3.5" aria-hidden />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
