"use client";

import { Button, Dialog, DialogContent, Form, FormField, Input, Select, toast } from "@hirevion/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useRef } from "react";
import { Controller, useForm } from "react-hook-form";
import { inviteUser } from "@/admin/api";
import { AccessChoice, CheckboxGroup } from "@/admin/fields";
import { useAdminProblem } from "@/admin/problems";
import { keys, useRoles, useTeams } from "@/admin/queries";
import { useRoleName } from "@/admin/role-name";
import { useStepUp } from "@/admin/step-up";
import { z } from "@/config/zod";

const LOCALES = ["en-IN", "en-US"] as const;

/** Invites someone: an email with a link to set their password (needs step-up). */
export function InviteDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("admin.users");
  const common = useTranslations("admin.common");
  const roleName = useRoleName();
  const roles = useRoles();
  const teams = useTeams();
  const withStepUp = useStepUp();
  const problems = useAdminProblem();
  const queryClient = useQueryClient();
  // One key per invitation, reused if it's retried (ADR-0010 idempotency).
  const key = useRef(crypto.randomUUID());

  const schema = useMemo(
    () =>
      z.object({
        email: z.string().trim().min(1, t("emailRequired")),
        name: z.string().trim().min(1, t("nameRequired")),
        role_ids: z.array(z.string()).min(1, t("rolesRequired")),
        team_ids: z.array(z.string()),
        access_scope: z.enum(["organization", "teams"]),
        locale: z.enum(LOCALES),
      }),
    [t],
  );
  type Values = z.infer<typeof schema>;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: "",
      name: "",
      role_ids: [],
      team_ids: [],
      access_scope: "organization",
      locale: "en-IN",
    },
  });

  async function submit(values: Values) {
    try {
      await withStepUp(() => inviteUser(values, key.current));
    } catch (error) {
      const placed = problems.onForm(form, error, {
        email: "email",
        name: "name",
        role_ids: "role_ids",
        team_ids: "team_ids",
      });
      if (!placed) problems.show(error);
      return;
    }
    toast.success(t("sent", { email: values.email }), {});
    await queryClient.invalidateQueries({ queryKey: keys.users });
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        title={t("inviteTitle")}
        description={t("inviteDescription")}
        closeLabel={common("close")}
        className="w-[min(40rem,calc(100vw-2rem))]"
      >
        <Form form={form} onSubmit={submit}>
          <FormField
            control={form.control}
            name="email"
            label={t("email")}
            render={(field) => <Input type="email" autoComplete="off" {...field} />}
          />
          <FormField
            control={form.control}
            name="name"
            label={t("name")}
            render={(field) => <Input autoComplete="off" {...field} />}
          />
          <Controller
            control={form.control}
            name="role_ids"
            render={({ field, fieldState }) => (
              <CheckboxGroup
                legend={t("roles")}
                options={(roles.data ?? []).map((role) => ({
                  value: role.id,
                  label: roleName(role),
                }))}
                value={field.value}
                onChange={field.onChange}
                error={fieldState.error?.message}
              />
            )}
          />
          <Controller
            control={form.control}
            name="team_ids"
            render={({ field, fieldState }) => (
              <CheckboxGroup
                legend={t("teams")}
                options={(teams.data ?? []).map((team) => ({ value: team.id, label: team.name }))}
                value={field.value}
                onChange={field.onChange}
                error={fieldState.error?.message}
                emptyText={t("noTeams")}
              />
            )}
          />
          <Controller
            control={form.control}
            name="access_scope"
            render={({ field }) => <AccessChoice value={field.value} onChange={field.onChange} />}
          />
          <FormField
            control={form.control}
            name="locale"
            label={t("language")}
            render={(field) => (
              <Select
                id={field.id}
                aria-invalid={field["aria-invalid"]}
                options={LOCALES.map((locale) => ({
                  value: locale,
                  label: common(`languages.${locale}`),
                }))}
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
              {t("send")}
            </Button>
          </div>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
