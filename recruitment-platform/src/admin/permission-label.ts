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
