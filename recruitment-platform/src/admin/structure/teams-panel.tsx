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
  Select,
  Skeleton,
  Switch,
  Textarea,
  toast,
} from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, UsersRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useId, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import {
  addTeamMember,
  createTeam,
  listTeamMembers,
  listUsers,
  removeTeamMember,
  type Team,
  updateTeam,
} from "@/admin/api";
import { useAdminProblem } from "@/admin/problems";
import { keys, useDepartments, useTeams } from "@/admin/queries";
import { z } from "@/config/zod";

const NO_DEPARTMENT = "none";

/** PRD §9 teams: who works together, and what someone limited to their teams sees. */
export function TeamsPanel() {
  const t = useTranslations("admin.teams");
  const common = useTranslations("admin.common");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const switchId = useId();
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState<Team | "new" | null>(null);
  const [members, setMembers] = useState<Team | null>(null);
  const teams = useTeams(showArchived);

  const archive = useMutation({
    mutationFn: (team: Team) => updateTeam(team.id, { archived: team.archived_at === null }),
    onSuccess: (saved) => {
      toast.success(
        t(saved.archived_at ? "archivedToast" : "restoredToast", { name: saved.name }),
        {},
      );
      void queryClient.invalidateQueries({ queryKey: keys.teams });
    },
    onError: problems.show,
  });

  if (teams.isError) {
    return (
      <p role="alert" className="text-danger text-sm">
        {common("loadFailed")}
      </p>
    );
  }

  const rows = teams.data ?? [];
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
      {teams.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState icon={<UsersRound />} title={t("emptyTitle")} description={t("emptyHint")} />
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
                  {t("department")}
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  {t("members")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <span className="sr-only">{common("edit")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((team) => (
                <tr key={team.id} className="border-border border-t">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2 font-medium">
                      {team.name}
                      {team.archived_at ? <Badge>{common("archived")}</Badge> : null}
                    </div>
                    {team.description ? (
                      <div className="text-muted-foreground text-xs">{team.description}</div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">{team.department_name ?? "—"}</td>
                  <td className="px-3 py-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t("manageMembers", { name: team.name })}
                      onClick={() => setMembers(team)}
                    >
                      {t("memberCount", { count: team.member_count })}
                    </Button>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={common("editNamed", { name: team.name })}
                        onClick={() => setEditing(team)}
                      >
                        {common("edit")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={archive.isPending}
                        aria-label={common(team.archived_at ? "restoreNamed" : "archiveNamed", {
                          name: team.name,
                        })}
                        onClick={() => archive.mutate(team)}
                      >
                        {common(team.archived_at ? "restore" : "archive")}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing ? (
        <TeamDialog team={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      ) : null}
      {members ? <TeamMembersDialog team={members} onClose={() => setMembers(null)} /> : null}
    </div>
  );
}

function TeamDialog({ team, onClose }: { team: Team | null; onClose: () => void }) {
  const t = useTranslations("admin.teams");
  const common = useTranslations("admin.common");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const departments = useDepartments();
  const key = useRef(crypto.randomUUID());
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, common("nameRequired")),
        description: z.string(),
        department_id: z.string(),
      }),
    [common],
  );
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: team?.name ?? "",
      description: team?.description ?? "",
      department_id: team?.department_id ?? NO_DEPARTMENT,
    },
  });

  async function submit(values: Values) {
    const body = {
      name: values.name.trim(),
      description: values.description.trim() || null,
      department_id: values.department_id === NO_DEPARTMENT ? null : values.department_id,
    };
    try {
      if (team) await updateTeam(team.id, body);
      else {
        await createTeam(body, key.current);
        toast.success(t("created", { name: body.name }), {});
      }
    } catch (error) {
      const placed = problems.onForm(form, error, {
        name: "name",
        description: "description",
        department_id: "department_id",
      });
      if (!placed) problems.show(error);
      return;
    }
    await queryClient.invalidateQueries({ queryKey: keys.teams });
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={team ? t("editTitle", { name: team.name }) : t("createTitle")}
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
          <FormField
            control={form.control}
            name="department_id"
            label={t("department")}
            render={(field) => (
              <Select
                id={field.id}
                aria-invalid={field["aria-invalid"]}
                options={[
                  { value: NO_DEPARTMENT, label: t("noDepartment") },
                  ...(departments.data ?? []).map((department) => ({
                    value: department.id,
                    label: department.name,
                  })),
                ]}
                value={field.value}
                onValueChange={field.onChange}
              />
            )}
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

function TeamMembersDialog({ team, onClose }: { team: Team; onClose: () => void }) {
  const t = useTranslations("admin.teams");
  const common = useTranslations("admin.common");
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const members = useQuery({
    queryKey: keys.teamMembers(team.id),
    queryFn: () => listTeamMembers(team.id),
  });
  const found = useQuery({
    queryKey: [...keys.users, { q: query, limit: 10 }],
    queryFn: () => listUsers({ q: query, limit: 10 }),
    enabled: query.length > 0,
  });

  function changed() {
    void queryClient.invalidateQueries({ queryKey: keys.teamMembers(team.id) });
    void queryClient.invalidateQueries({ queryKey: keys.teams });
  }
  const add = useMutation({
    mutationFn: (userId: string) => addTeamMember(team.id, userId),
    onSuccess: changed,
    onError: problems.show,
  });
  const remove = useMutation({
    mutationFn: (userId: string) => removeTeamMember(team.id, userId),
    onSuccess: changed,
    onError: problems.show,
  });

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setQuery(search.trim());
  }

  const memberIds = new Set((members.data ?? []).map((member) => member.id));
  const candidates = (found.data?.items ?? []).filter((user) => !memberIds.has(user.id));

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={t("membersTitle", { name: team.name })}
        description={t("membersDescription")}
        closeLabel={common("close")}
      >
        <div className="flex flex-col gap-4">
          {members.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : (members.data ?? []).length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noMembers")}</p>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border">
              {(members.data ?? []).map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <div className="grid">
                    <span className="text-sm">{member.name}</span>
                    <span className="text-muted-foreground text-xs">{member.email}</span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={remove.isPending}
                    aria-label={t("remove", { name: member.name })}
                    onClick={() => remove.mutate(member.id)}
                  >
                    {t("removeShort")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {team.archived_at ? (
            <p className="text-muted-foreground text-sm">{t("archivedNoMembers")}</p>
          ) : (
            <div className="flex flex-col gap-2">
              <form onSubmit={submitSearch}>
                <Input
                  type="search"
                  aria-label={t("findPeople")}
                  placeholder={t("findPeople")}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </form>
              {query && found.data ? (
                candidates.length === 0 ? (
                  <p className="text-muted-foreground text-sm">{t("noMatches")}</p>
                ) : (
                  <ul className="grid gap-1">
                    {candidates.map((user) => (
                      <li key={user.id} className="flex items-center justify-between gap-2">
                        <span className="text-sm">
                          {user.name}{" "}
                          <span className="text-muted-foreground text-xs">{user.email}</span>
                        </span>
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={add.isPending}
                          aria-label={t("add", { name: user.name })}
                          onClick={() => add.mutate(user.id)}
                        >
                          {t("addPeople")}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )
              ) : null}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
