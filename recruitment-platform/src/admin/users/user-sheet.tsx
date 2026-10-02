"use client";

import { Badge, Button, Input, Label, Sheet, SheetContent, Skeleton, toast } from "@hirevion/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";
import {
  cancelInvitation,
  disableUser,
  enableUser,
  getUser,
  resendInvitation,
  setUserRoles,
  type User,
  updateUser,
} from "@/admin/api";
import { AccessChoice, CheckboxGroup } from "@/admin/fields";
import { useAdminProblem } from "@/admin/problems";
import { keys, useRoles, useTeams } from "@/admin/queries";
import { useRoleName } from "@/admin/role-name";
import { useStepUp } from "@/admin/step-up";

export const STATUS_TONES = { active: "success", invited: "info", disabled: "neutral" } as const;

/** One user: their details and teams, their roles, and whether they can sign in. */
export function UserSheet({ userId, onClose }: { userId: string; onClose: () => void }) {
  const t = useTranslations("admin.users");
  const common = useTranslations("admin.common");
  const user = useQuery({ queryKey: keys.user(userId), queryFn: () => getUser(userId) });

  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent
        title={user.data?.name ?? t("loading")}
        {...(user.data ? { description: user.data.email } : {})}
        closeLabel={common("close")}
        className="w-[min(32rem,100vw)]"
      >
        {user.data ? (
          <UserDetails user={user.data} onClose={onClose} />
        ) : user.isError ? (
          <p role="alert" className="text-danger text-sm">
            {common("loadFailed")}
          </p>
        ) : (
          <Skeleton className="h-48 w-full" />
        )}
      </SheetContent>
    </Sheet>
  );
}

function UserDetails({ user, onClose }: { user: User; onClose: () => void }) {
  const t = useTranslations("admin.users");
  const roleName = useRoleName();
  const roles = useRoles();
  const teams = useTeams();
  const withStepUp = useStepUp();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  const nameId = useId();

  const [name, setName] = useState(user.name);
  const [scope, setScope] = useState(user.access_scope);
  const [teamIds, setTeamIds] = useState(() => user.teams.map((team) => team.id));
  const [roleIds, setRoleIds] = useState(() => user.roles.map((role) => role.id));
  useEffect(() => {
    setName(user.name);
    setScope(user.access_scope);
    setTeamIds(user.teams.map((team) => team.id));
    setRoleIds(user.roles.map((role) => role.id));
  }, [user]);

  function refreshed(next: User) {
    queryClient.setQueryData(keys.user(next.id), next);
    void queryClient.invalidateQueries({ queryKey: keys.users });
  }

  const saveDetails = useMutation({
    mutationFn: () => updateUser(user.id, { name, access_scope: scope, team_ids: teamIds }),
    onSuccess: (next) => {
      refreshed(next);
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });
  const saveRoles = useMutation({
    mutationFn: () => withStepUp(() => setUserRoles(user.id, roleIds)),
    onSuccess: (next) => {
      refreshed(next);
      toast.success(t("saved"), {});
    },
    onError: problems.show,
  });
  const toggle = useMutation({
    mutationFn: () =>
      withStepUp(() => (user.status === "disabled" ? enableUser(user.id) : disableUser(user.id))),
    onSuccess: (next) => {
      refreshed(next);
      toast.success(
        t(next.status === "disabled" ? "disabled" : "enabled", { name: next.name }),
        {},
      );
    },
    onError: problems.show,
  });
  const resend = useMutation({
    mutationFn: () => withStepUp(() => resendInvitation(user.id)),
    onSuccess: () => toast.success(t("resent", { email: user.email }), {}),
    onError: problems.show,
  });
  const cancel = useMutation({
    mutationFn: () => withStepUp(() => cancelInvitation(user.id)),
    onSuccess: () => {
      toast.success(t("cancelled", { email: user.email }), {});
      void queryClient.invalidateQueries({ queryKey: keys.users });
      onClose();
    },
    onError: problems.show,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={STATUS_TONES[user.status]}>{t(`statuses.${user.status}`)}</Badge>
        {user.status === "invited" ? (
          <span className="text-muted-foreground text-sm">{t("invitedNote")}</span>
        ) : user.status === "disabled" ? (
          <span className="text-muted-foreground text-sm">{t("disabledNote")}</span>
        ) : null}
      </div>

      <section aria-labelledby={`${nameId}-details`} className="grid gap-4">
        <h3 id={`${nameId}-details`} className="font-medium">
          {t("details")}
        </h3>
        <div className="grid gap-1.5">
          <Label htmlFor={nameId}>{t("name")}</Label>
          <Input id={nameId} value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <AccessChoice value={scope} onChange={setScope} />
        <CheckboxGroup
          legend={t("teams")}
          options={(teams.data ?? []).map((team) => ({ value: team.id, label: team.name }))}
          value={teamIds}
          onChange={setTeamIds}
          emptyText={t("noTeams")}
        />
        <div>
          <Button
            variant="secondary"
            disabled={saveDetails.isPending || !name.trim()}
            onClick={() => saveDetails.mutate()}
          >
            {t("saveDetails")}
          </Button>
        </div>
      </section>

      <section className="grid gap-4">
        <CheckboxGroup
          legend={t("roles")}
          options={(roles.data ?? []).map((role) => ({ value: role.id, label: roleName(role) }))}
          value={roleIds}
          onChange={setRoleIds}
          error={roleIds.length === 0 ? t("rolesRequired") : undefined}
        />
        <div>
          <Button
            variant="secondary"
            disabled={saveRoles.isPending || roleIds.length === 0}
            onClick={() => saveRoles.mutate()}
          >
            {t("saveRoles")}
          </Button>
        </div>
      </section>

      <div className="flex flex-wrap gap-2 border-border border-t pt-4">
        {user.status === "invited" ? (
          <>
            <Button variant="secondary" disabled={resend.isPending} onClick={() => resend.mutate()}>
              {t("resend")}
            </Button>
            <Button variant="danger" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              {t("cancelInvitation")}
            </Button>
          </>
        ) : (
          <Button
            variant={user.status === "disabled" ? "secondary" : "danger"}
            disabled={toggle.isPending}
            onClick={() => toggle.mutate()}
          >
            {t(user.status === "disabled" ? "enable" : "disable")}
          </Button>
        )}
      </div>
    </div>
  );
}
