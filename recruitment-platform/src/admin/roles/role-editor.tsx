"use client";

import {
  Button,
  Dialog,
  DialogContent,
  Form,
  FormField,
  Input,
  Textarea,
  toast,
} from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useRef } from "react";
import { Controller, useForm } from "react-hook-form";
import {
  type CataloguePermission,
  createRole,
  deleteRole,
  type Role,
  updateRole,
} from "@/admin/api";
import { CheckboxGroup } from "@/admin/fields";
import { byArea, permissionLabelKey } from "@/admin/permission-label";
import { useAdminProblem } from "@/admin/problems";
import { keys } from "@/admin/queries";
import { useStepUp } from "@/admin/step-up";
import type { Permission } from "@/auth/permissions";
import { z } from "@/config/zod";

// Everyone manages their own account, whatever their roles, so it isn't a choice here.
const EVERYONE: readonly string[] = ["account.manage"];

interface RoleEditorProps {
  /** The custom role to edit, or null to create one. */
  role: Role | null;
  catalogue: readonly CataloguePermission[];
  /** What the signed-in user holds: they can't grant anything else. */
  held: readonly Permission[];
  onClose: () => void;
}

export function RoleEditor({ role, catalogue, held, onClose }: RoleEditorProps) {
  const t = useTranslations("admin.roles");
  const common = useTranslations("admin.common");
  const labels = useTranslations("permissionLabels");
  const areas = useTranslations("permissionAreas");
  const withStepUp = useStepUp();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const key = useRef(crypto.randomUUID());

  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, t("nameRequired")),
        description: z.string(),
        permissions: z.array(z.string()),
      }),
    [t],
  );
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: role?.name ?? "",
      description: role?.description ?? "",
      permissions: (role?.permissions ?? []).filter((p) => !EVERYONE.includes(p)),
    },
  });

  const choices = catalogue.filter((entry) => !EVERYONE.includes(entry.name));
  const grouped = byArea(choices);

  async function submit(values: Values) {
    const body = {
      name: values.name.trim(),
      description: values.description.trim() || null,
      // In catalogue order, so the request (and the audit) reads the same each time.
      permissions: choices
        .map((entry) => entry.name)
        .filter((name) => values.permissions.includes(name)),
    };
    try {
      if (role) await withStepUp(() => updateRole(role.id, body));
      else await withStepUp(() => createRole(body, key.current));
    } catch (error) {
      if (!problems.onForm(form, error, { name: "name", permissions: "permissions" })) {
        problems.show(error);
      }
      return;
    }
    if (!role) toast.success(t("created", { name: body.name }), {});
    await queryClient.invalidateQueries({ queryKey: keys.roles });
    onClose();
  }

  async function remove() {
    if (!role) return;
    try {
      await withStepUp(() => deleteRole(role.id));
    } catch (error) {
      problems.show(error);
      return;
    }
    toast.success(t("deleted", { name: role.name }), {});
    await queryClient.invalidateQueries({ queryKey: keys.roles });
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={role ? t("editTitle", { name: role.name }) : t("createTitle")}
        description={t("editorDescription")}
        closeLabel={common("close")}
        className="max-h-[calc(100vh-2rem)] w-[min(44rem,calc(100vw-2rem))] overflow-y-auto"
      >
        <Form form={form} onSubmit={submit}>
          <FormField
            control={form.control}
            name="name"
            label={common("name")}
            render={(field) => <Input autoComplete="off" {...field} />}
          />
          <FormField
            control={form.control}
            name="description"
            label={common("description")}
            render={(field) => <Textarea rows={2} {...field} />}
          />
          <Controller
            control={form.control}
            name="permissions"
            render={({ field, fieldState }) => (
              <div className="grid gap-4">
                <p className="font-medium text-sm">{t("permissions")}</p>
                {grouped.map(([area, entries]) => (
                  <CheckboxGroup
                    key={area}
                    legend={areas(area as "jobs")}
                    options={entries.map((entry) => {
                      const mine = held.includes(entry.name as Permission);
                      return {
                        value: entry.name,
                        label: labels(permissionLabelKey(entry.name) as "jobs_view"),
                        disabled: !mine,
                        ...(mine ? {} : { hint: t("notYours") }),
                      };
                    })}
                    value={field.value}
                    onChange={field.onChange}
                  />
                ))}
                {fieldState.error?.message ? (
                  <p role="alert" className="text-danger text-sm">
                    {fieldState.error.message}
                  </p>
                ) : null}
              </div>
            )}
          />
          <div className="flex flex-wrap justify-between gap-2">
            <div>
              {role && role.member_count === 0 ? (
                <Button type="button" variant="danger" onClick={remove}>
                  {t("delete")}
                </Button>
              ) : null}
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>
                {common("cancel")}
              </Button>
              <Button type="submit" disabled={form.formState.isSubmitting}>
                {t("save")}
              </Button>
            </div>
          </div>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
