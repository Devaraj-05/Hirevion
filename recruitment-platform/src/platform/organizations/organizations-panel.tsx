"use client";

import {
  Badge,
  Button,
  DataTable,
  type DataTableColumn,
  Dialog,
  DialogContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  Form,
  FormField,
  Input,
  localViewStore,
  Select,
  Textarea,
  toast,
} from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building, MoreHorizontal, Plus } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import {
  createOrganization,
  inviteOrganizationAdmin,
  listOrganizations,
  type OrganizationListing,
  reactivateOrganization,
  suspendOrganization,
} from "@/admin/api";
import { useAdminProblem } from "@/admin/problems";
import { keys } from "@/admin/queries";
import { useStepUp } from "@/admin/step-up";
import { z } from "@/config/zod";
import { Pager } from "@/data/pager";
import { useCursorPage } from "@/data/use-cursor-page";
import { useUrlTableState } from "@/data/use-url-table-state";
import { useTableLabels } from "@/page/use-table-labels";

/** The reserved organisation that holds the super admins: it can't be suspended or changed. */
export const PLATFORM_ORGANIZATION_ID = "00000000-0000-7000-8000-000000000001";
const FILTERS = ["status", "q"] as const;
const ANY = "all";
const PAGE_SIZE = 25;
const organizationName = (organization: OrganizationListing) => organization.name;

/** A slug suggested from a name: lower-case letters, digits and single hyphens. */
export function suggestSlug(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/g, "");
}

type Dialogs =
  | { kind: "create" }
  | { kind: "suspend"; organization: OrganizationListing }
  | { kind: "invite"; organization: OrganizationListing };

/** PRD §6 Super Admin: every organisation, and creating, suspending and reactivating them. */
export function OrganizationsPanel() {
  const t = useTranslations("platform.organizations");
  const format = useFormatter();
  const labels = useTableLabels(organizationName);
  const withStepUp = useStepUp();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const [search, setSearch] = useState(filters.q ?? "");
  const [dialog, setDialog] = useState<Dialogs | null>(null);

  const query = {
    status: filters.status as OrganizationListing["status"] | undefined,
    q: filters.q,
  };
  const page = useCursorPage([...keys.organizations, query], (cursor) =>
    listOrganizations({ ...query, cursor, limit: PAGE_SIZE }),
  );

  const reactivate = useMutation({
    mutationFn: (organization: OrganizationListing) =>
      withStepUp(() => reactivateOrganization(organization.id)),
    onSuccess: (saved) => {
      toast.success(t("reactivated", { name: saved.name }), {});
      void queryClient.invalidateQueries({ queryKey: keys.organizations });
    },
    onError: problems.show,
  });

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setFilters({ ...filters, q: search.trim() });
  }

  const columns = useMemo<DataTableColumn<OrganizationListing>[]>(
    () => [
      {
        id: "name",
        header: t("name"),
        hideable: false,
        cell: (organization) => (
          <div className="grid">
            <span className="font-medium">{organization.name}</span>
            <span className="text-muted-foreground text-xs">{organization.slug}</span>
          </div>
        ),
      },
      {
        id: "status",
        header: t("status"),
        cell: (organization) => (
          <Badge tone={organization.status === "active" ? "success" : "warning"}>
            {t(`statuses.${organization.status}`)}
          </Badge>
        ),
      },
      { id: "users", header: t("users"), cell: (organization) => organization.user_count },
      {
        id: "created",
        header: t("created"),
        cell: (organization) =>
          format.dateTime(new Date(organization.created_at), { dateStyle: "medium" }),
      },
      {
        id: "actions",
        header: t("actionsColumn"),
        hideable: false,
        cell: (organization) =>
          organization.id === PLATFORM_ORGANIZATION_ID ? (
            <span className="text-muted-foreground text-xs">{t("platformRow")}</span>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("actions", { name: organization.name })}
                >
                  <MoreHorizontal className="size-4" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {organization.status === "active" ? (
                  <DropdownMenuItem onSelect={() => setDialog({ kind: "suspend", organization })}>
                    {t("suspend")}
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onSelect={() => reactivate.mutate(organization)}>
                    {t("reactivate")}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => setDialog({ kind: "invite", organization })}>
                  {t("inviteAdmin")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ),
      },
    ],
    [t, format, reactivate],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <form onSubmit={submitSearch} className="min-w-56 flex-1">
          <Input
            type="search"
            aria-label={t("search")}
            placeholder={t("search")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </form>
        <Select
          aria-label={t("status")}
          className="w-40"
          value={filters.status ?? ANY}
          onValueChange={(value) => setFilters({ ...filters, status: value === ANY ? "" : value })}
          options={[
            { value: ANY, label: t("anyStatus") },
            { value: "active", label: t("statuses.active") },
            { value: "suspended", label: t("statuses.suspended") },
          ]}
        />
        <Button onClick={() => setDialog({ kind: "create" })}>
          <Plus className="size-4" aria-hidden />
          {t("new")}
        </Button>
      </div>
      <DataTable
        tableId="platform-organizations"
        caption={t("caption")}
        columns={columns}
        rows={page.rows}
        getRowId={(organization) => organization.id}
        labels={labels}
        sorting={sorting}
        onSortingChange={setSorting}
        filters={filters}
        onFiltersChange={setFilters}
        viewStore={viewStore}
        emptyState={
          page.isLoading ? null : (
            <EmptyState icon={<Building />} title={t("emptyTitle")} description={t("emptyHint")} />
          )
        }
        footer={
          <Pager
            hasPrevious={page.hasPrevious}
            hasNext={page.hasNext}
            onPrevious={page.previousPage}
            onNext={page.nextPage}
          />
        }
      />
      {dialog?.kind === "create" ? (
        <CreateOrganizationDialog onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "suspend" ? (
        <SuspendDialog organization={dialog.organization} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "invite" ? (
        <InviteAdminDialog organization={dialog.organization} onClose={() => setDialog(null)} />
      ) : null}
    </div>
  );
}

function CreateOrganizationDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("platform.organizations");
  const common = useTranslations("admin.common");
  const withStepUp = useStepUp();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const key = useRef(crypto.randomUUID());
  const slugEdited = useRef(false);
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, t("nameRequired")),
        slug: z.string().trim().min(1, t("slugRequired")),
        admin_name: z.string().trim().min(1, t("adminNameRequired")),
        admin_email: z.string().trim().min(1, t("adminEmailRequired")),
      }),
    [t],
  );
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", slug: "", admin_name: "", admin_email: "" },
  });

  async function submit(values: Values) {
    try {
      await withStepUp(() => createOrganization(values, key.current));
    } catch (error) {
      const placed = problems.onForm(form, error, {
        name: "name",
        slug: "slug",
        admin_name: "admin_name",
        admin_email: "admin_email",
      });
      if (!placed) problems.show(error);
      return;
    }
    toast.success(t("createdToast", { name: values.name, email: values.admin_email }), {});
    await queryClient.invalidateQueries({ queryKey: keys.organizations });
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={t("createTitle")}
        description={t("createDescription")}
        closeLabel={common("close")}
      >
        <Form form={form} onSubmit={submit}>
          <FormField
            control={form.control}
            name="name"
            label={t("name")}
            render={(field) => (
              <Input
                autoComplete="off"
                {...field}
                onChange={(event) => {
                  field.onChange(event);
                  if (!slugEdited.current) {
                    form.setValue("slug", suggestSlug(event.target.value));
                  }
                }}
              />
            )}
          />
          <FormField
            control={form.control}
            name="slug"
            label={t("slug")}
            description={t("slugHint")}
            render={(field) => (
              <Input
                autoComplete="off"
                {...field}
                onChange={(event) => {
                  slugEdited.current = true;
                  field.onChange(event);
                }}
              />
            )}
          />
          <FormField
            control={form.control}
            name="admin_name"
            label={t("adminName")}
            render={(field) => <Input autoComplete="off" {...field} />}
          />
          <FormField
            control={form.control}
            name="admin_email"
            label={t("adminEmail")}
            render={(field) => <Input type="email" autoComplete="off" {...field} />}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {common("cancel")}
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {common("create")}
            </Button>
          </div>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

function SuspendDialog({
  organization,
  onClose,
}: {
  organization: OrganizationListing;
  onClose: () => void;
}) {
  const t = useTranslations("platform.organizations");
  const common = useTranslations("admin.common");
  const withStepUp = useStepUp();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const form = useForm<{ reason: string }>({ defaultValues: { reason: "" } });

  async function submit(values: { reason: string }) {
    try {
      await withStepUp(() => suspendOrganization(organization.id, values.reason.trim() || null));
    } catch (error) {
      problems.show(error);
      return;
    }
    toast.success(t("suspended", { name: organization.name }), {});
    await queryClient.invalidateQueries({ queryKey: keys.organizations });
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={t("suspendTitle", { name: organization.name })}
        description={t("suspendDescription")}
        closeLabel={common("close")}
      >
        <Form form={form} onSubmit={submit}>
          <FormField
            control={form.control}
            name="reason"
            label={t("reason")}
            description={t("reasonHint")}
            render={(field) => <Textarea rows={2} maxLength={500} {...field} />}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {common("cancel")}
            </Button>
            <Button type="submit" variant="danger" disabled={form.formState.isSubmitting}>
              {t("suspend")}
            </Button>
          </div>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

function InviteAdminDialog({
  organization,
  onClose,
}: {
  organization: OrganizationListing;
  onClose: () => void;
}) {
  const t = useTranslations("platform.organizations");
  const users = useTranslations("admin.users");
  const common = useTranslations("admin.common");
  const withStepUp = useStepUp();
  const problems = useAdminProblem();
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, users("nameRequired")),
        email: z.string().trim().min(1, users("emailRequired")),
      }),
    [users],
  );
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "" },
  });

  async function submit(values: Values) {
    try {
      await withStepUp(() => inviteOrganizationAdmin(organization.id, values));
    } catch (error) {
      if (!problems.onForm(form, error, { name: "name", email: "email" })) problems.show(error);
      return;
    }
    toast.success(t("invited", { email: values.email }), {});
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={t("inviteTitle", { name: organization.name })}
        description={t("inviteDescription")}
        closeLabel={common("close")}
      >
        <Form form={form} onSubmit={submit}>
          <FormField
            control={form.control}
            name="name"
            label={users("name")}
            render={(field) => <Input autoComplete="off" {...field} />}
          />
          <FormField
            control={form.control}
            name="email"
            label={users("email")}
            render={(field) => <Input type="email" autoComplete="off" {...field} />}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {common("cancel")}
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {users("send")}
            </Button>
          </div>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
