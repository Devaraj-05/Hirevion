"use client";

import { Badge, Button, Skeleton } from "@hirevion/ui";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { listPermissions, type Role } from "@/admin/api";
import { keys, useRoles } from "@/admin/queries";
import { useRoleName } from "@/admin/role-name";
import type { Permission } from "@/auth/permissions";
import { PermissionMatrix } from "./permission-matrix";
import { RoleEditor } from "./role-editor";

/** Built-in and custom roles, the matrix of what each grants, and the custom-role editor. */
export function RolesPanel({ held }: { held: readonly Permission[] }) {
  const t = useTranslations("admin.roles");
  const common = useTranslations("admin.common");
  const roleName = useRoleName();
  const roles = useRoles();
  const catalogue = useQuery({ queryKey: keys.permissions, queryFn: listPermissions });
  const [editing, setEditing] = useState<Role | "new" | null>(null);
  const matrixId = useId();

  if (roles.isError || catalogue.isError) {
    return (
      <p role="alert" className="text-danger text-sm">
        {common("loadFailed")}
      </p>
    );
  }
  if (!roles.data || !catalogue.data) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div className="flex justify-end">
          <Button onClick={() => setEditing("new")}>
            <Plus className="size-4" aria-hidden />
            {t("newRole")}
          </Button>
        </div>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("listTitle")}</caption>
            <thead className="bg-surface-muted">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {common("name")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {common("description")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("permissions")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <span className="sr-only">{common("edit")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {roles.data.map((role) => (
                <tr key={role.id} className="border-border border-t">
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{roleName(role)}</span>
                      <Badge tone={role.system ? "neutral" : "accent"}>
                        {role.system ? t("builtIn") : t("custom")}
                      </Badge>
                      <span className="text-muted-foreground text-xs">
                        {t("members", { count: role.member_count })}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{role.description}</td>
                  <td className="px-3 py-2 text-muted-foreground">{role.permissions.length}</td>
                  <td className="px-3 py-2 text-right">
                    {role.system ? null : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(role)}
                        aria-label={t("edit", { name: role.name })}
                      >
                        {common("edit")}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-muted-foreground text-sm">{t("builtInNote")}</p>
      </section>

      <section aria-labelledby={matrixId} className="flex flex-col gap-3">
        <h2 id={matrixId} className="font-semibold text-lg">
          {t("matrixTitle")}
        </h2>
        <PermissionMatrix roles={roles.data} catalogue={catalogue.data} />
      </section>

      {editing ? (
        <RoleEditor
          role={editing === "new" ? null : editing}
          catalogue={catalogue.data}
          held={held}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  );
}
