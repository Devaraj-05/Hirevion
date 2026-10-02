import type { Permission } from "@/auth/permissions";

/** A permission's key in `permissionLabels`: next-intl reads dots as nesting, so they become
 * underscores (`admin.users.manage` → `admin_users_manage`). */
export function permissionLabelKey(permission: Permission | string): string {
  return permission.replaceAll(".", "_");
}

/** The area a permission belongs to, for grouping (`reports.interview.view` → `reports`). */
export function permissionArea(permission: Permission | string): string {
  return permission.split(".", 1)[0] ?? permission;
}

/** Catalogue entries grouped by area, areas and entries keeping their catalogue order. */
export function byArea<T extends { area: string }>(entries: readonly T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const entry of entries) {
    const group = groups.get(entry.area);
    if (group) group.push(entry);
    else groups.set(entry.area, [entry]);
  }
  return [...groups];
}
