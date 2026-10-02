"use client";

import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  EmptyState,
  Form,
  FormField,
  Input,
  Label,
  Skeleton,
  Switch,
  Textarea,
  toast,
} from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { createDepartment, type Department, updateDepartment } from "@/admin/api";
import { useAdminProblem } from "@/admin/problems";
import { keys, useDepartments, useTeams } from "@/admin/queries";
import { z } from "@/config/zod";

/** PRD §9 departments: created, renamed, archived and restored, never deleted. */
export function DepartmentsPanel() {
  const t = useTranslations("admin.departments");
  const common = useTranslations("admin.common");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const switchId = useId();
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState<Department | "new" | null>(null);
  const departments = useDepartments(showArchived);
  const teams = useTeams(true);

  const archive = useMutation({
    mutationFn: (department: Department) =>
      updateDepartment(department.id, { archived: department.archived_at === null }),
    onSuccess: (saved) => {
      toast.success(
        t(saved.archived_at ? "archivedToast" : "restoredToast", { name: saved.name }),
        {},
      );
      void queryClient.invalidateQueries({ queryKey: keys.departments });
    },
    onError: problems.show,
  });

  if (departments.isError) {
    return (
      <p role="alert" className="text-danger text-sm">
        {common("loadFailed")}
      </p>
    );
  }

  const rows = departments.data ?? [];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Switch id={switchId} checked={showArchived} onCheckedChange={setShowArchived} />
          <Label htmlFor={switchId}>{common("showArchived")}</Label>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus className="size-4" aria-hidden />
          {t("new")}
        </Button>
      </div>
      {departments.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Building2 />} title={t("emptyTitle")} description={t("emptyHint")} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("caption")}</caption>
            <thead className="bg-surface-muted">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {common("name")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("teams")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("status")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <span className="sr-only">{common("edit")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((department) => (
                <tr key={department.id} className="border-border border-t">
                  <td className="px-3 py-2">
                    <div className="font-medium">{department.name}</div>
                    {department.description ? (
                      <div className="text-muted-foreground text-xs">{department.description}</div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    {
                      (teams.data ?? []).filter((team) => team.department_id === department.id)
                        .length
                    }
                  </td>
                  <td className="px-3 py-2">
                    {department.archived_at ? (
                      <Badge>{common("archived")}</Badge>
                    ) : (
                      <Badge tone="success">{t("active")}</Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={common("editNamed", { name: department.name })}
                        onClick={() => setEditing(department)}
                      >
                        {common("edit")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={archive.isPending}
                        aria-label={common(
                          department.archived_at ? "restoreNamed" : "archiveNamed",
                          { name: department.name },
                        )}
                        onClick={() => archive.mutate(department)}
                      >
                        {common(department.archived_at ? "restore" : "archive")}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-muted-foreground text-sm">{t("archiveHint")}</p>
      {editing ? (
        <DepartmentDialog
          department={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  );
}

function DepartmentDialog({
  department,
  onClose,
}: {
  department: Department | null;
  onClose: () => void;
}) {
  const t = useTranslations("admin.departments");
  const common = useTranslations("admin.common");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const key = useRef(crypto.randomUUID());
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, common("nameRequired")),
        description: z.string(),
      }),
    [common],
  );
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: department?.name ?? "", description: department?.description ?? "" },
  });

  async function submit(values: Values) {
    const body = { name: values.name.trim(), description: values.description.trim() || null };
    try {
      if (department) await updateDepartment(department.id, body);
      else {
        await createDepartment(body, key.current);
        toast.success(t("created", { name: body.name }), {});
      }
    } catch (error) {
      if (!problems.onForm(form, error, { name: "name", description: "description" })) {
        problems.show(error);
      }
      return;
    }
    await queryClient.invalidateQueries({ queryKey: keys.departments });
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={department ? t("editTitle", { name: department.name }) : t("createTitle")}
        closeLabel={common("close")}
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
            description={common("optional")}
            render={(field) => <Textarea rows={2} {...field} />}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {common("cancel")}
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {common("save")}
            </Button>
          </div>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
