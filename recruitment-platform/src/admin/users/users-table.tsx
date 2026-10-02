"use client";

import {
  Badge,
  Button,
  DataTable,
  type DataTableColumn,
  EmptyState,
  Input,
  localViewStore,
  Select,
} from "@hirevion/ui";
import { UserPlus, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useMemo, useState } from "react";
import { listUsers, type User } from "@/admin/api";
import { keys, useRoles, useTeams } from "@/admin/queries";
import { useRoleName } from "@/admin/role-name";
import { Pager } from "@/data/pager";
import { useCursorPage } from "@/data/use-cursor-page";
import { useUrlTableState } from "@/data/use-url-table-state";
import { useTableLabels } from "@/page/use-table-labels";
import { InviteDialog } from "./invite-dialog";
import { STATUS_TONES, UserSheet } from "./user-sheet";

const FILTERS = ["status", "role", "team", "q"] as const;
const ANY = "all";
const PAGE_SIZE = 25;
const userName = (user: User) => user.name;

/** The organisation's users: filters in the URL, invitations, and one user at a time. */
export function UsersTable() {
  const t = useTranslations("admin.users");
  const labels = useTableLabels(userName);
  const roleName = useRoleName();
  const roles = useRoles();
  const teams = useTeams();
  const { sorting, setSorting, filters, setFilters } = useUrlTableState(FILTERS);
  const viewStore = useMemo(() => localViewStore(), []);
  const [inviting, setInviting] = useState(false);
  const [openUser, setOpenUser] = useState<string | null>(null);
  const [search, setSearch] = useState(filters.q ?? "");

  const query = {
    status: filters.status as User["status"] | undefined,
    role_id: filters.role,
    team_id: filters.team,
    q: filters.q,
  };
  const page = useCursorPage([...keys.users, query], (cursor) =>
    listUsers({ ...query, cursor, limit: PAGE_SIZE }),
  );

  function setFilter(key: (typeof FILTERS)[number], value: string) {
    setFilters({ ...filters, [key]: value === ANY ? "" : value });
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setFilter("q", search.trim());
  }

  const columns = useMemo<DataTableColumn<User>[]>(
    () => [
      {
        id: "name",
        header: t("name"),
        hideable: false,
        cell: (user) => (
          <button
            type="button"
            onClick={() => setOpenUser(user.id)}
            aria-label={t("open", { name: user.name })}
            className="grid text-left hover:underline focus-visible:underline"
          >
            <span className="font-medium">{user.name}</span>
            <span className="text-muted-foreground text-xs">{user.email}</span>
          </button>
        ),
      },
      {
        id: "roles",
        header: t("roles"),
        cell: (user) => user.roles.map(roleName).join(", "),
      },
      {
        id: "teams",
        header: t("teams"),
        cell: (user) => user.teams.map((team) => team.name).join(", "),
      },
      {
        id: "status",
        header: t("status"),
        cell: (user) => (
          <Badge tone={STATUS_TONES[user.status]}>{t(`statuses.${user.status}`)}</Badge>
        ),
      },
      {
        id: "access",
        header: t("access"),
        cell: (user) => t(`scopes.${user.access_scope}`),
      },
    ],
    [t, roleName],
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
          onValueChange={(value) => setFilter("status", value)}
          options={[
            { value: ANY, label: t("anyStatus") },
            ...(["active", "invited", "disabled"] as const).map((status) => ({
              value: status,
              label: t(`statuses.${status}`),
            })),
          ]}
        />
        <Select
          aria-label={t("roles")}
          className="w-48"
          value={filters.role ?? ANY}
          onValueChange={(value) => setFilter("role", value)}
          options={[
            { value: ANY, label: t("anyRole") },
            ...(roles.data ?? []).map((role) => ({ value: role.id, label: roleName(role) })),
          ]}
        />
        <Select
          aria-label={t("teams")}
          className="w-48"
          value={filters.team ?? ANY}
          onValueChange={(value) => setFilter("team", value)}
          options={[
            { value: ANY, label: t("anyTeam") },
            ...(teams.data ?? []).map((team) => ({ value: team.id, label: team.name })),
          ]}
        />
        <Button onClick={() => setInviting(true)}>
          <UserPlus className="size-4" aria-hidden />
          {t("invite")}
        </Button>
      </div>
      <DataTable
        tableId="admin-users"
        caption={t("caption")}
        columns={columns}
        rows={page.rows}
        getRowId={(user) => user.id}
        labels={labels}
        sorting={sorting}
        onSortingChange={setSorting}
        filters={filters}
        onFiltersChange={setFilters}
        viewStore={viewStore}
        emptyState={
          page.isLoading ? null : (
            <EmptyState icon={<Users />} title={t("emptyTitle")} description={t("emptyHint")} />
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
      {inviting ? <InviteDialog onClose={() => setInviting(false)} /> : null}
      {openUser ? <UserSheet userId={openUser} onClose={() => setOpenUser(null)} /> : null}
    </div>
  );
}
