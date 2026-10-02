"use client";

import { Check, Minus } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment } from "react";
import type { CataloguePermission, Role } from "@/admin/api";
import { byArea, permissionLabelKey } from "@/admin/permission-label";
import { useRoleName } from "@/admin/role-name";

/** Which role grants which permission: a permission per row (grouped by area), a role per
 * column. Every cell says "Granted" or "Not granted" to screen readers. */
export function PermissionMatrix({
  roles,
  catalogue,
}: {
  roles: readonly Role[];
  catalogue: readonly CataloguePermission[];
}) {
  const t = useTranslations("admin.roles");
  const labels = useTranslations("permissionLabels");
  const areas = useTranslations("permissionAreas");
  const roleName = useRoleName();
  const grouped = byArea(catalogue);

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <caption className="sr-only">{t("matrixCaption")}</caption>
        <thead className="bg-surface-muted">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("permission")}
            </th>
            {roles.map((role) => (
              <th key={role.id} scope="col" className="px-3 py-2 text-center font-medium">
                {roleName(role)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grouped.map(([area, entries]) => (
            <Fragment key={area}>
              <tr className="border-border border-t bg-surface-sunken">
                <th
                  scope="colgroup"
                  colSpan={roles.length + 1}
                  className="px-3 py-1.5 text-left font-semibold text-xs uppercase tracking-wide"
                >
                  {areas(area as "jobs")}
                </th>
              </tr>
              {entries.map((entry) => (
                <tr key={entry.name} className="border-border border-t">
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    {labels(permissionLabelKey(entry.name) as "jobs_view")}
                  </th>
                  {roles.map((role) => {
                    const granted = role.permissions.includes(entry.name);
                    return (
                      <td key={role.id} className="px-3 py-2 text-center">
                        {granted ? (
                          <Check className="inline size-4 text-success" aria-hidden />
                        ) : (
                          <Minus className="inline size-4 text-muted-foreground" aria-hidden />
                        )}
                        <span className="sr-only">{granted ? t("granted") : t("notGranted")}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
